"""Tests for the CSV reader, PDF report, and billing reconciliation tools."""

import csv
import io
import json

from challenge.tools.billing_reconciler import BillingReconciliationTool, reconcile_billing
from challenge.tools.csv_reader import CSVReaderTool, read_csv_source
from challenge.tools.pdf_report import PDFReportTool


class TestCSVReader:
    def test_list_sources(self):
        """CSVReaderTool returns error with available sources for unknown source."""
        tool = CSVReaderTool()
        result = tool.forward(source="nonexistent")
        assert "ERROR" in result
        assert "accounts" in result

    def test_read_accounts(self):
        """Can read the accounts CSV."""
        rows = read_csv_source("accounts")
        assert len(rows) > 0
        assert "account_id" in rows[0]

    def test_read_accounts_tool(self):
        """CSVReaderTool returns formatted output for accounts."""
        tool = CSVReaderTool()
        result = tool.forward(source="accounts")
        assert "MERID-001" in result
        assert "rows from 'accounts'" in result

    def test_filter_by_account_id(self):
        """Can filter rows by account_id."""
        rows = read_csv_source("accounts", account_id="MERID-001")
        assert len(rows) == 1
        assert rows[0]["account_id"] == "MERID-001"

    def test_read_billing(self):
        """Can read billing data."""
        rows = read_csv_source("billing", limit=5)
        assert len(rows) <= 5
        assert len(rows) > 0

    def test_limit(self):
        """Limit parameter caps the number of rows."""
        rows = read_csv_source("billing", limit=3)
        assert len(rows) <= 3

    def test_all_sources_readable(self):
        """All registered data sources can be read."""
        from challenge.tools.csv_reader import DATA_SOURCES

        for source_name in DATA_SOURCES:
            rows = read_csv_source(source_name, limit=1)
            assert len(rows) >= 1, f"Source '{source_name}' returned no rows"


class TestPDFReport:
    def test_create_simple_report(self, tmp_path):
        """PDFReportTool creates a PDF file."""
        tool = PDFReportTool()

        # Override output dir for test
        import challenge.tools.pdf_report as pdf_module

        original_dir = pdf_module.OUTPUT_DIR
        pdf_module.OUTPUT_DIR = tmp_path

        try:
            sections = [
                {"type": "heading", "text": "Test Report"},
                {"type": "paragraph", "text": "This is a test paragraph."},
                {
                    "type": "table",
                    "headers": ["Name", "Value"],
                    "rows": [["Alpha", "100"], ["Beta", "200"]],
                },
            ]
            result = tool.forward(
                title="Test Report",
                filename="test_report.pdf",
                content_sections_json=json.dumps(sections),
            )
            assert "Report saved" in result
            assert (tmp_path / "test_report.pdf").exists()
            assert (tmp_path / "test_report.pdf").stat().st_size > 0
        finally:
            pdf_module.OUTPUT_DIR = original_dir

    def test_invalid_json(self):
        """PDFReportTool handles invalid JSON gracefully."""
        tool = PDFReportTool()
        result = tool.forward(
            title="Test",
            filename="test.pdf",
            content_sections_json="not valid json",
        )
        assert "ERROR" in result

    def test_non_array_json(self):
        """PDFReportTool rejects non-array JSON."""
        tool = PDFReportTool()
        result = tool.forward(
            title="Test",
            filename="test.pdf",
            content_sections_json='{"type": "heading"}',
        )
        assert "ERROR" in result

    def test_report_with_chart(self, tmp_path):
        """PDFReportTool can render charts."""
        tool = PDFReportTool()

        import challenge.tools.pdf_report as pdf_module

        original_dir = pdf_module.OUTPUT_DIR
        pdf_module.OUTPUT_DIR = tmp_path

        try:
            sections = [
                {"type": "heading", "text": "Chart Report"},
                {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Test Chart",
                    "labels": ["Q1", "Q2", "Q3"],
                    "datasets": [{"label": "Revenue", "data": [100, 150, 200]}],
                },
            ]
            result = tool.forward(
                title="Chart Report",
                filename="chart_report.pdf",
                content_sections_json=json.dumps(sections),
            )
            assert "Report saved" in result
            assert (tmp_path / "chart_report.pdf").exists()
        finally:
            pdf_module.OUTPUT_DIR = original_dir


class TestBillingReconciler:
    def test_deduplicates_reissued_invoice(self):
        """INV-2025-MH-022 was issued twice at different amounts; only one
        payment was received, matching the first issuance. Reconciliation
        must use that amount once, not sum both issuances."""
        result = reconcile_billing("MERID-001")
        anomaly_text = " ".join(result["anomalies"])
        assert "INV-2025-MH-022" in anomaly_text
        assert "18583.58" in anomaly_text

    def test_excludes_undocumented_adjustment_from_totals(self):
        """The verbal, not-yet-credited -1854.00 adjustment on
        INV-2026-MH-027 must be surfaced as an anomaly, not netted into
        total_invoiced or total_paid."""
        result = reconcile_billing("MERID-001")
        anomaly_text = " ".join(result["anomalies"])
        assert "BIL-5228" in anomaly_text
        assert "-1854" in anomaly_text

    def test_does_not_flag_immaterial_rounding_adjustment(self):
        """The 1-cent rounding fix on INV-2024-MH-005 is noise, not a
        finding — it should not appear in the anomalies list."""
        result = reconcile_billing("MERID-001")
        anomaly_text = " ".join(result["anomalies"])
        assert "BIL-5021" not in anomaly_text

    def test_totals_are_lower_than_naive_sum(self):
        """Guard against regressing to the naive 'sum every invoice_issued
        row' approach that double-counts the reissued invoice."""
        rows = read_csv_source("billing", account_id="MERID-001", limit=10_000)
        naive_total = sum(float(r["amount"]) for r in rows if r["event_type"] == "invoice_issued")
        result = reconcile_billing("MERID-001")
        assert result["total_invoiced"] < naive_total

    def test_reconciliation_totals(self):
        """End-to-end totals for MERID-001, hand-verified against the raw log
        and against the PDF report generated from a live agent run."""
        result = reconcile_billing("MERID-001")
        assert result["invoice_count"] == 28
        assert result["total_invoiced"] == 509852.11
        assert result["total_paid"] == 454101.37
        assert result["outstanding_balance"] == 55750.74

    def test_tool_forward_returns_parseable_csv(self):
        """BillingReconciliationTool.forward must return CSV an agent can
        parse with csv.reader into real numbers — not a pretty-printed
        block that gets indexed like a tuple or text-parsed by hand."""
        tool = BillingReconciliationTool()
        output = tool.forward(account_id="MERID-001")

        rows = list(csv.reader(io.StringIO(output)))
        assert rows[0] == ["field", "value"]
        summary = {r[0]: r[1] for r in rows[1:] if r[0] != "anomaly"}
        anomalies = [r[1] for r in rows[1:] if r[0] == "anomaly"]

        assert float(summary["total_invoiced"]) == 509852.11
        assert float(summary["total_paid"]) == 454101.37
        assert float(summary["outstanding_balance"]) == 55750.74
        assert int(summary["invoice_count"]) == 28
        assert any("INV-2025-MH-022" in a for a in anomalies)
