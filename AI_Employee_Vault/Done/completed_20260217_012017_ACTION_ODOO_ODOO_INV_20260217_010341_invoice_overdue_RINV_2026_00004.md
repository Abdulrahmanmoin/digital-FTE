---
type: odoo_action
odoo_model: "account.move"
record_id: "16"
record_name: "RINV/2026/00004"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_RINV_2026_00004.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — RINV/2026/00004

## Summary
A customer credit note (refund) for **$20,375.00** issued to **Acme Corporation** became overdue on 2026-02-14 and has not been paid or reconciled as of today (2026-02-17). This means Acme Corporation is owed $20,375.00 that has not yet been disbursed or applied.

## Urgency: HIGH
Overdue by 3 days on a large customer credit note ($20,375.00) with no human assignee and no recorded source/origin. Acme Corporation may be actively waiting on this refund.

## Recommended Actions
- **Investigate origin**: Open Odoo → Accounting → Customers → Credit Notes → RINV/2026/00004. Determine what return, dispute, or transaction triggered this credit note (no source/origin is recorded — verify it is legitimate).
- **Reconcile or refund**:
  - If Acme Corporation has open outstanding invoices → apply the credit note as reconciliation in Odoo.
  - If no open invoices → process a cash refund of $20,375.00 to Acme Corporation and register the payment in Odoo.
- **Reassign from OdooBot**: Assign RINV/2026/00004 to the responsible account manager or finance team member in Odoo.
- **Contact Acme Corporation**: Notify them whether a refund is being issued or the credit will be applied to future invoices.
- **Mark as settled in Odoo**: Once the refund or reconciliation is completed, confirm the credit note payment status updates to `paid` or `in_payment`.

## Context
- Document type is `out_refund` (Customer Credit Note) — this is money **we owe to the customer**, not money owed to us.
- Due date was 2026-02-14; today is 2026-02-17 — 3 days overdue.
- Currently assigned to OdooBot (no human owner has taken responsibility).
- No source/origin field is populated — the reason for the credit note is unknown from the data alone. Manual verification is required to confirm legitimacy before issuing a $20,375.00 refund.
- At this amount, internal approval thresholds may apply — consult finance manager if required.
