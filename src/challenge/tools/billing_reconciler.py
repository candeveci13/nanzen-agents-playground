"""BillingReconciliationTool - produces a reconciled billing summary for one account.

The raw `billing` event log is not a clean ledger: a single invoice can have
more than one `invoice_issued` row (corrections/reissues), and credit notes
appear both as their own lifecycle events (`credit_note_issued`,
`credit_applied` — keyed by the credit note's own id, not the invoice) and
netted directly into the invoice they were applied to (via `credit_note_ref`).
Summing every row's `amount` therefore double-counts credits and can
double-count reissued invoices. This produces one canonical amount per real
invoice_id and totals only those, surfacing everything else as an anomaly
instead of folding it into a total.
"""

from __future__ import annotations

from smolagents import Tool

from challenge.tools.csv_reader import read_csv_source

# Below this, a rounding-only adjustment isn't worth flagging to a human.
MATERIAL_ADJUSTMENT_THRESHOLD = 1.00


def reconcile_billing(account_id: str) -> dict:
    """Reconcile the billing event log for one account into a clean summary."""
    rows = read_csv_source("billing", account_id=account_id, limit=10_000)

    issued_by_invoice: dict[str, list[dict]] = {}
    paid_by_invoice: dict[str, float] = {}
    anomalies: list[str] = []

    for row in rows:
        invoice_id = row.get("invoice_id", "")
        event_type = row["event_type"]

        if event_type == "invoice_issued" and invoice_id.startswith("INV-"):
            issued_by_invoice.setdefault(invoice_id, []).append(row)
        elif event_type in ("payment_received", "refund_completed") and invoice_id.startswith(
            "INV-"
        ):
            paid_by_invoice[invoice_id] = paid_by_invoice.get(invoice_id, 0.0) + float(
                row["amount"]
            )
        elif event_type in ("credit_note_issued", "credit_applied"):
            anomalies.append(
                f"{row['event_id']} ({event_type}, {invoice_id}, {row['amount']}): "
                f"{row['notes']} — not double-counted, credit is netted into the "
                "invoice it was applied to."
            )
        elif event_type == "adjustment":
            amount = float(row["amount"])
            if abs(amount) >= MATERIAL_ADJUSTMENT_THRESHOLD:
                anomalies.append(
                    f"{row['event_id']} (adjustment, {invoice_id}, {amount}): "
                    f"{row['notes']} — not reflected in any total below."
                )

    canonical_amounts: dict[str, float] = {}
    for invoice_id, issued_rows in issued_by_invoice.items():
        amounts = [float(r["amount"]) for r in issued_rows]
        if len(issued_rows) == 1:
            canonical_amounts[invoice_id] = amounts[0]
            continue

        paid = paid_by_invoice.get(invoice_id)
        match = next((a for a in amounts if paid is not None and abs(a - paid) < 0.01), None)
        canonical = match if match is not None else amounts[-1]
        canonical_amounts[invoice_id] = canonical
        reason = (
            "matches payment received"
            if match is not None
            else "most recent issuance, no matching payment"
        )
        anomalies.append(
            f"{invoice_id}: issued {len(issued_rows)} times with amounts {amounts} "
            f"— using {canonical:.2f} ({reason})."
        )

    total_invoiced = round(sum(canonical_amounts.values()), 2)
    total_paid = round(sum(paid_by_invoice.values()), 2)

    return {
        "account_id": account_id,
        "invoice_count": len(canonical_amounts),
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "outstanding_balance": round(total_invoiced - total_paid, 2),
        "anomalies": anomalies,
    }


class BillingReconciliationTool(Tool):
    """Tool for agents to get a reconciled (deduplicated, netted) billing summary."""

    name = "reconcile_billing"
    description = (
        "Reconcile the raw billing event log for one account into clean totals. "
        "Use this instead of manually summing rows from read_context('billing') — "
        "the raw log can contain more than one invoice_issued row per invoice and "
        "represents credit notes in multiple places, so summing raw amounts "
        "overcounts. Returns invoice_count, total_invoiced, total_paid, "
        "outstanding_balance, and a list of anomalies worth mentioning in a report "
        "(reissued invoices, credit notes, and material undocumented adjustments)."
    )
    inputs = {
        "account_id": {
            "type": "string",
            "description": "Account to reconcile, e.g. 'MERID-001'.",
        },
    }
    output_type = "string"

    def forward(self, account_id: str) -> str:
        result = reconcile_billing(account_id)
        lines = [
            f"Reconciled billing for {result['account_id']}:",
            f"  Invoice count: {result['invoice_count']}",
            f"  Total invoiced: {result['total_invoiced']:.2f}",
            f"  Total paid: {result['total_paid']:.2f}",
            f"  Outstanding balance: {result['outstanding_balance']:.2f}",
        ]
        if result["anomalies"]:
            lines.append("  Anomalies:")
            lines.extend(f"    - {a}" for a in result["anomalies"])
        else:
            lines.append("  Anomalies: none")
        return "\n".join(lines)
