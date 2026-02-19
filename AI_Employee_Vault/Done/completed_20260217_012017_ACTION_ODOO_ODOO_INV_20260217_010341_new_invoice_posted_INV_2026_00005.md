---
type: odoo_action
odoo_model: "account.move"
record_id: "5"
record_name: "INV/2026/00005"
event_type: "new_invoice_posted"
urgency: "medium"
source_task: "ODOO_INV_20260217_010341_new_invoice_posted_INV_2026_00005.md"
status: pending_approval
---

# Odoo Event: new_invoice_posted — INV/2026/00005

## Summary
A new customer invoice INV/2026/00005 for **OpenWood** totalling **$2,000.00** has been posted in Odoo. The invoice is unpaid with a due date of **2026-02-28** (11 days from now), and was originally dated 2026-01-05 — over 6 weeks ago — suggesting a delayed posting that warrants immediate follow-up.

## Urgency: MEDIUM
The due date is approaching in 11 days. The ~6 week gap between invoice date and posting date means the customer may not yet have been notified, making prompt outreach important to avoid a late payment.

## Recommended Actions
- **Verify invoice delivery**: Check in Odoo whether INV/2026/00005 was sent to OpenWood. Go to: Accounting > Customers > Invoices > INV/2026/00005 > Send & Print (if not already sent).
- **Send payment reminder to OpenWood**: Contact the customer to confirm receipt of the invoice and remind them of the due date (2026-02-28).
- **Investigate posting delay**: Follow up with Marc Demo (assigned user) on why this January 5 invoice was only posted on February 16. Confirm it is not a duplicate or accidental backdated entry.
- **Register payment once received**: After OpenWood pays, register payment in Odoo: Accounting > Customers > Invoices > INV/2026/00005 > Register Payment.

## Context
- Invoice date: 2026-01-05 | Posted: 2026-02-16 | Due: 2026-02-28
- Assigned to: Marc Demo
- No linked source order (Origin field is empty) — may be worth verifying this invoice is tied to a legitimate transaction.
- Amount is $2,000.00 — moderate, but important for cash flow given the delayed posting.
