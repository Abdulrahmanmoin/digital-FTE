---
type: odoo_action
odoo_model: "account.move"
record_id: "11"
record_name: "INV/2026/00009"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_INV_2026_00009.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — INV/2026/00009

## Summary
Customer invoice INV/2026/00009 for OpenWood totalling $1,799.00 is overdue by 3 days (due 2026-02-14, unpaid as of 2026-02-17). The full amount remains outstanding with no payment or prior follow-up recorded.

## Urgency: HIGH
Invoice is 3 days past due with the full $1,799.00 still outstanding and no prior reminder on record. Immediate outreach is needed to prevent further aging.

## Recommended Actions
- Send a payment reminder email to OpenWood's accounts payable contact referencing invoice INV/2026/00009, amount $1,799.00, due date 2026-02-14
- Verify OpenWood contact details in Odoo: Accounting > Customers > OpenWood
- Log the outreach attempt in the invoice chatter in Odoo for audit trail
- If no response within 48 hours, escalate to account manager or issue a formal overdue notice
- Register payment in Odoo once funds are received: Accounting > Customers > Invoices > INV/2026/00009 > Register Payment

## Context
- Invoice issued: 2026-02-09 | Due: 2026-02-14 | Detected overdue: 2026-02-17
- Payment terms appear to be 5 days (issued to due date gap)
- No internal notes recorded on the invoice — this is likely the first follow-up opportunity
- Odoo record ID: 11 (account.move model)
- No partial payments received — amount_due equals amount_total ($1,799.00)
