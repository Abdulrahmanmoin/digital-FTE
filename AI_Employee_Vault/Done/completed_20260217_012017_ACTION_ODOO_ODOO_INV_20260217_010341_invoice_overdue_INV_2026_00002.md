---
type: odoo_action
odoo_model: "account.move"
record_id: "2"
record_name: "INV/2026/00002"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_INV_2026_00002.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — INV/2026/00002

## Summary
Customer invoice INV/2026/00002 for **Acme Corporation** totalling **$46,250.00** was due on
2026-02-14 and remains fully unpaid as of 2026-02-17 — it is 3 days overdue with no payment
registered in Odoo.

## Urgency: HIGH
Invoice is 3 days past due for a significant amount ($46,250.00). No partial payment has been
received and no internal notes indicate a reminder has already been sent. Immediate follow-up
is required to avoid further delay in collection.

## Recommended Actions
- Send a payment reminder email to **Acme Corporation** accounts payable, referencing invoice
  **INV/2026/00002**, amount **$46,250.00**, and due date **2026-02-14**
- Verify in Odoo that no payment was misapplied or missed:
  Accounting > Customers > Invoices > INV/2026/00002 > Review payment status
- Check Acme Corporation's contact record for the correct AP contact / email
- Register payment in Odoo once funds are received:
  Accounting > Customers > Invoices > INV/2026/00002 > Register Payment
- Set a 3-business-day follow-up reminder; escalate to account manager if no response

## Context
- Invoice date: 2026-02-12 | Due date: 2026-02-14 (2-day payment term — unusually short)
- Full amount of $46,250.00 is outstanding — no partial payment recorded
- No source/origin order linked on the invoice; no assigned owner
- Odoo record last modified: 2026-02-16 17:17:56 (may indicate a recent manual update worth reviewing)
- Early-stage overdue: polite professional reminder is appropriate before escalating to collections
