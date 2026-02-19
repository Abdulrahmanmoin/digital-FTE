---
type: odoo_action
odoo_model: "account.move"
record_id: "15"
record_name: "RINV/2026/00003"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_RINV_2026_00003.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — RINV/2026/00003

## Summary
A customer credit note (refund) for **$31,750.00** owed to **Acme Corporation** has gone overdue — it was due on 2026-02-14 and the full amount remains unprocessed as of 2026-02-17.

## Urgency: HIGH
This is a liability owed to a customer, overdue by 3 days, with the full $31,750.00 still outstanding and no source document linked. Large amount + customer-facing obligation warrants immediate attention.

## Recommended Actions
- **Investigate the credit note origin:** Open Odoo > Accounting > Customers > Credit Notes > RINV/2026/00003. Determine why the refund was issued (returned goods, billing error, pricing dispute, etc.) — no source/origin is currently linked.
- **Contact Acme Corporation:** Reach out to confirm they are aware of the pending credit and agree on the settlement method (offset vs. cash refund).
- **Reconcile or pay out the credit note in Odoo:**
  - *If offsetting against open invoices:* Accounting > Customers > Credit Notes > RINV/2026/00003 > click "Add Outstanding Credits" or match to an open invoice.
  - *If issuing a cash refund:* Accounting > Customers > Credit Notes > RINV/2026/00003 > Register Payment.
- **Reassign record from OdooBot** to the responsible AR/finance team member for accountability.
- **Escalate if amount or dispute is unresolved:** $31,750 is a significant liability — escalate to finance manager if the underlying reason is disputed or unclear.

## Context
- **Document type:** `out_refund` (Customer Credit Note) — this is money the business owes to Acme Corporation, not a receivable.
- **Due date:** 2026-02-14 (3 days overdue).
- **Amount:** $31,750.00 — full balance outstanding, no partial payments applied.
- **No source document linked** — the origin of this credit note is unknown; could indicate a return, a dispute, or a manual entry that needs verification.
- **Assigned to OdooBot** — no human owner currently; may have been missed in normal AR review.
- Delaying resolution risks customer dissatisfaction and accounting period-end discrepancies.
