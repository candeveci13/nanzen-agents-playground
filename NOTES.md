# Solution guide

A skim-friendly walkthrough of this PR — start here before diving into the
diff or the deeper logs.

## The bug

The account manager's hunch was right. `billing_summary` summed every row in
`data/billing.csv` naively, but that log isn't a clean ledger:

- Some invoices have **more than one `invoice_issued` row** — `INV-2025-MH-022`
  was reissued at €270 more than the original after the customer's AP portal
  didn't show it. Summing both rows double-counts one real invoice.
- **Credit notes appear in up to three places** — as their own
  `credit_note_issued`/`credit_applied` events, and netted directly into the
  invoice amount they were applied to. Summing all of them subtracts the same
  credit multiple times.
- One **undocumented verbal adjustment** (-€1,854, agreed with the customer
  but never credited) was sitting in the data with no visibility.

## The fix, in the order it happened

1. **`src/challenge/tools/billing_reconciler.py`** (new) — `reconcile_billing()`
   canonicalizes to one amount per real invoice (matching a reissue against
   whichever amount the payment actually confirms), nets each credit exactly
   once, and surfaces the undocumented adjustment as a named finding instead
   of silently folding it into a total.
2. **`src/challenge/runner.py` / `src/challenge/tasks.py`** — wired the tool
   into the `billing_summary` task and rewrote its prompt to require using it
   instead of hand-summing raw rows.
3. **`src/challenge/tools/pdf_report.py`** — fixed a second, unrelated bug
   found while verifying the output PDF: long table cells overflowed the page
   instead of wrapping.
4. **`tests/test_tools.py`** — 6 new tests pinning down the reconciliation
   math (dedup, credit netting, the naive-sum regression guard) and the
   tool's output format.

## Verifying it

Ran `make run ARGS="--task billing_summary"` end to end and checked the
generated PDF's text (`pdftotext`) against the reconciliation by hand:

```
total invoiced:      €509,852.11
total paid:           €454,101.37
outstanding balance:   €55,750.74
```

## If you want more detail

Two working documents I kept alongside the code, each with a different job:

- **`roadmap.md`** is the plan — written before touching code, then checked
  off as each step landed. It answers "what was the intended scope, and did
  it get done?" It also has a "Left alone on purpose" section and a
  "Follow-ups found, deliberately documented instead of fixed" section: a
  self-review pass (plus a couple more live runs) turned up more issues than
  the timebox allows fixing, so instead of quietly expanding scope, they're
  written down there with a fix sketch each — for whoever picks this up
  next.
- **`logs/2026-08-30.md`** is the journal — a chronological account of what
  actually happened while doing the work: what was investigated, which live
  agent runs failed and why, what the fix was and how it was verified. It
  answers "how did we get here?" rather than "what's the plan?" If you want
  to see the reasoning behind a specific decision (e.g. why the
  reconciliation tool's output format changed from JSON to CSV), it's in
  here, in the order it happened.

Read `roadmap.md` first for the shape of the work; drop into `logs/2026-08-30.md`
for the reasoning behind any specific piece of it.

## What I'd do with more time / left alone on purpose

- More time: fix `CSVReaderTool`'s silent `limit=50` truncation (all 8 data
  sources, not just billing); surface the one resolved dispute
  `reconcile_billing` currently drops silently; replace
  `PDFReportTool`/`BillingReconciliationTool`'s JSON-string/CSV-text
  interfaces with native Python objects — built and confirmed this last one
  works, then reverted it to stay in scope.
- Left alone on purpose: `usage_trends`/`support_health` (untouched); no
  generalized reconciliation engine — billing data only exists for
  MERID-001 today.
- Time spent went past the stated 30-60 minutes (three debugged live-agent
  runs, the reconciliation tool, the PDF fix, and a self-review pass).
  Judged it worth it since both the original numbers bug and a real
  rendering bug needed fixing for something a customer would actually see.
