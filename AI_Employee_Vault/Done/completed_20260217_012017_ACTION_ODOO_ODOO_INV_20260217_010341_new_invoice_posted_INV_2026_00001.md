---
type: odoo_action
odoo_model: "account.move"
record_id: "1"
record_name: "INV/2026/00001"
event_type: "new_invoice_posted"
urgency: "medium"
source_task: "ODOO_INV_20260217_010341_new_invoice_posted_INV_2026_00001.md"
status: pending_approval
---

# Odoo Event: new_invoice_posted — INV/2026/00001

## Summary
A new customer invoice (INV/2026/00001) for **Azure Interior** totalling **$31,750.00** has been confirmed and posted in Odoo. It is currently unpaid with a due date of **2026-03-31**.

## Urgency: MEDIUM
Invoice is not yet overdue — due in 42 days. However, the large amount ($31,750) warrants prompt dispatch and proactive follow-up to set clear payment expectations with the customer.

## Recommended Actions
- **Send the invoice to Azure Interior** — Odoo: *Accounting > Customers > Invoices > INV/2026/00001 > Send & Print* (if not already sent)
- **Verify the linked Sales Order** — The Source/Origin field is blank; confirm this invoice was expected and not created in error
- **Notify Marc Demo** — Confirm the assigned user (Marc Demo) is aware the invoice is posted and has been sent to the customer
- **Add an internal note** in Odoo confirming dispatch date and the contact person at Azure Interior
- **Schedule payment follow-up** — Set a reminder for ~2026-03-24 (1 week before due) to chase payment if not yet received
- **Register payment in Odoo** once funds are received: *Accounting > Customers > Invoices > INV/2026/00001 > Register Payment*

## Context
- Invoice dated: 2026-02-01 | Due date: 2026-03-31
- Customer: Azure Interior | Assigned to: Marc Demo
- Full amount of $31,750.00 remains outstanding — no partial payment recorded
- No linked sales order detected (Source/Origin blank) — manual verification recommended
- If unpaid by 2026-03-31, an `invoice_overdue` event will be triggered and urgency will escalate to HIGH
