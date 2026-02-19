---
type: odoo_action
odoo_model: "account.move"
record_id: "10"
record_name: "INV/2026/00008"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_INV_2026_00008.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — INV/2026/00008

## Summary
Customer invoice INV/2026/00008 issued to **LightsUp** for **$750.00** is 3 days overdue (due 2026-02-14) with no payment received and no prior follow-up recorded in Odoo.

## Urgency: HIGH
Full amount outstanding, due date already passed, and no evidence of any reminder or payment arrangement on file.

## Recommended Actions
- Send a payment reminder email to **LightsUp** referencing invoice **INV/2026/00008**, amount **$750.00**, and due date **2026-02-14**.
- Log a Chatter note in Odoo on record INV/2026/00008 documenting the reminder sent and the date.
- If no response within 3–5 business days, send a formal overdue notice or escalate internally.
- Once payment is received, register it in Odoo: **Accounting > Customers > Invoices > INV/2026/00008 > Register Payment**.

## Context
- Invoice type: Customer Invoice (out_invoice)
- Current state: Posted (Confirmed) — legally issued, awaiting payment
- Payment state: Not Paid — no partial payment recorded
- No assigned owner or internal notes exist on this record; proactive outreach is needed
- Last write date in Odoo: 2026-02-16, suggesting the record has not been updated since it was posted
