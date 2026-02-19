---
type: odoo_action
odoo_model: "account.move"
record_id: "6"
record_name: "INV/2026/00006"
event_type: "new_invoice_posted"
urgency: "medium"
source_task: "ODOO_INV_20260217_010341_new_invoice_posted_INV_2026_00006.md"
status: pending_approval
---

# Odoo Event: new_invoice_posted — INV/2026/00006

## Summary
A new customer invoice INV/2026/00006 for **OpenWood** totalling **$1,000.00** has been posted in Odoo. It is fully unpaid with a due date of **2026-02-28** (11 days away), requiring proactive follow-up to prevent it becoming overdue.

## Urgency: MEDIUM
Invoice is not yet overdue but the due date is 11 days away with no payment received. Timely outreach now avoids a future overdue situation.

## Recommended Actions
- Send a payment reminder to **OpenWood** referencing invoice INV/2026/00006 for $1,000.00, due 2026-02-28
- Review invoice in Odoo: Accounting > Customers > Invoices > INV/2026/00006 — confirm line items and customer contact
- Assign follow-up to **Marc Demo** (assigned user on the invoice) with a deadline of 2026-02-24 if no payment is received
- Once payment is confirmed, register it in Odoo: Accounting > Customers > Invoices > INV/2026/00006 > Register Payment

## Context
- Invoice date is 2026-01-10 — the invoice is over a month old but was only just detected as posted (possibly backdated or delayed posting).
- No linked source order or internal notes on the record.
- Amount ($1,000.00) is moderate; standard collections process applies.
- If unpaid by due date, a separate `invoice_overdue` event will trigger escalation.
