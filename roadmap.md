# Roadmap — Part 1: MERID-001 billing summary

## Goal
Produce a billing summary for MERID-001 the account manager can put in front
of the customer, and fix whatever in the repo causes today's total to be
wrong.

## Plan

1. Write a small reconciliation pass over `billing` rows for one account:
   canonicalize to one row per `invoice_id` (latest `invoice_issued` wins,
   carry a flag when more than one exists), net credits exactly once, and
   separately surface un-applied/undocumented adjustments instead of folding
   them into a total.
2. Wire that into the billing summary — either as a small helper the agent's
   prompt tells it to use, or as a preprocessing step before the agent sees
   the data — so `read_context` on `billing` doesn't hand back a raw event
   stream for the agent to sum by hand.
3. Update the `billing_summary` task prompt/instructions to ask for: total
   invoiced (canonical, deduplicated), total paid, outstanding balance, and a
   called-out list of anomalies (the reissued invoice, the undocumented
   adjustment) — matching what the report should say, not just "sum
   invoices."
4. Re-run `make run ARGS="--task billing_summary"`, check the generated PDF's
   numbers against the reconciliation by hand.
5. Add/adjust a test asserting the reconciliation produces the correct
   deduplicated total for MERID-001 (guards against regressing to the naive
   sum).

## Left alone on purpose

- `usage_trends` and `support_health` tasks/tools — untouched, out of scope.
- No generalized reconciliation engine for arbitrary accounts — billing data
  only exists for MERID-001 right now, so scope the fix to what's needed
  here rather than building for hypothetical future accounts.
- No changes to `PDFReportTool` — the rendering pipeline is fine; the problem
  is the numbers going into it.
