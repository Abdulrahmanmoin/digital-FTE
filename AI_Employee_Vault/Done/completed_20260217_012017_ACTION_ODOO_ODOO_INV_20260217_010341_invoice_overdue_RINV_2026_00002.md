---
type: odoo_action
odoo_model: "account.move"
record_id: "13"
record_name: "RINV/2026/00002"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_RINV_2026_00002.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — RINV/2026/00002

## Summary
A Customer Credit Note (refund) of **$20,000.00** issued to **Azure Interior** became overdue on 2026-02-14 and remains unpaid. The business owes this refund to the customer and has not yet processed or applied it.

## Urgency: HIGH
Credit note is 3 days past due ($20,000 owed to Azure Interior). An unresolved refund obligation of this size risks damaging a key customer relationship and represents an outstanding liability on the books.

## Recommended Actions
1. **Verify legitimacy** — Check why this credit note was issued (no source/origin linked; assigned to OdooBot). Confirm the refund is approved and valid before processing.
2. **Option A — Register Refund Payment**: Odoo > Accounting > Customers > Credit Notes > RINV/2026/00002 > **Register Payment** — issue the $20,000 refund to Azure Interior.
3. **Option B — Offset Against Open Invoice**: If Azure Interior has outstanding invoices, navigate to one of those invoices and use **Outstanding Credits** to reconcile RINV/2026/00002 against what they owe — avoids cash outflow.
4. **Notify Azure Interior** if the refund has been delayed — send a brief email confirming the credit will be processed by [date] to maintain trust.
5. **Reassign from OdooBot** to the responsible accountant/owner in Odoo for proper tracking.

## Context
- **Document**: RINV/2026/00002 (Customer Credit Note)
- **Customer**: Azure Interior
- **Amount**: $20,000.00 (full amount outstanding — no partial payments recorded)
- **Invoice Date**: 2026-01-03 | **Due Date**: 2026-02-14 (3 days overdue)
- **Odoo Record ID**: 13 (account.move)
- No source/origin document is linked — the credit note may have been auto-generated. Investigate the underlying reason (return, dispute, billing error) before finalising payment method.
- Last write date in Odoo: 2026-02-16 — the record was recently touched, but payment status remains `not_paid`.
