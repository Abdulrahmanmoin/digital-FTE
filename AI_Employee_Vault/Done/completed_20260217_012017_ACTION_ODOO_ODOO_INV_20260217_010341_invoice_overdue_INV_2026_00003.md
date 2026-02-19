---
type: odoo_action
odoo_model: "account.move"
record_id: "3"
record_name: "INV/2026/00003"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_INV_2026_00003.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — INV/2026/00003

## Summary
Customer invoice INV/2026/00003 for Acme Corporation totalling $20,375.00 became due on 2026-02-14 and is now 3 days overdue with no payment received. Immediate follow-up is required.

## Urgency: HIGH
Invoice is fully unpaid, 3 days past due, and no prior reminder or internal note is on record. At $20,375.00 this is a material receivable requiring prompt action to prevent further aging.

## Recommended Actions
- **Send payment reminder email** to Acme Corporation referencing invoice INV/2026/00003, amount due $20,375.00, and original due date 2026-02-14. Request payment or an update on expected payment date.
- **Log the outreach in Odoo**: Accounting > Customers > Invoices > INV/2026/00003 > Log a note (chatter) documenting when and how the reminder was sent.
- **Register payment in Odoo** once funds are received: Accounting > Customers > Invoices > INV/2026/00003 > Register Payment.
- **Set a follow-up reminder** for 2026-02-20 (3 business days). If no response, escalate tone or involve management.
- **Verify Acme Corporation contact details** in Odoo (Partners > Acme Corporation) to ensure the reminder reaches the correct accounts payable contact.

## Context
- Invoice issued: 2026-02-11 | Due: 2026-02-14 | Now 3 days overdue (as of 2026-02-17).
- No assigned user or internal notes on the invoice — no one is currently tracking this.
- No source/origin document linked (standalone invoice, not tied to a confirmed sales order).
- If Acme Corporation has a history of late payments, consider adjusting credit terms for future invoices.
