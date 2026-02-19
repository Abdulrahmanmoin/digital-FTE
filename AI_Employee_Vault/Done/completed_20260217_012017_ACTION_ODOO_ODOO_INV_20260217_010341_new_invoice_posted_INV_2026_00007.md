---
type: odoo_action
odoo_model: "account.move"
record_id: "7"
record_name: "INV/2026/00007"
event_type: "new_invoice_posted"
urgency: "low"
source_task: "ODOO_INV_20260217_010341_new_invoice_posted_INV_2026_00007.md"
status: pending_approval
---

# Odoo Event: new_invoice_posted — INV/2026/00007

## Summary
A new customer invoice INV/2026/00007 for **OpenWood** totalling **$275.00** has been posted in Odoo and is currently unpaid, with a due date of **2026-02-28**.

## Urgency: LOW
Invoice is not yet overdue — due date is 11 days away (2026-02-28). Routine action is sufficient; no escalation needed at this stage.

## Recommended Actions
- **Send invoice to OpenWood**: Accounting > Customers > Invoices > INV/2026/00007 > "Send & Print" — confirm the customer has received the invoice.
- **Verify with Marc Demo**: Invoice date is 2026-01-14 but was only posted now; confirm whether OpenWood has already been notified.
- **Set a payment follow-up reminder**: Schedule a check-in around 2026-02-25 to confirm payment is on track before the due date.
- **Register payment when received**: Accounting > Customers > Invoices > INV/2026/00007 > "Register Payment" once OpenWood's payment arrives.

## Context
- Customer: **OpenWood**
- Invoice: **INV/2026/00007**
- Amount Due: **$275.00** (full balance outstanding)
- Due Date: **2026-02-28** (11 days from today)
- Assigned To: Marc Demo
- No linked sales order (Source/Origin is blank) — verify this is intentional.
- If payment is not received by the due date, this will become an overdue invoice and should be escalated.
