---
type: odoo_action
odoo_model: "sale.order"
record_id: "1"
record_name: "S00001"
event_type: "new_quotation"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_quotation_S00001.md"
status: pending_approval
---

# Odoo Event: new_quotation — S00001

## Summary
A new sales quotation (S00001) for **Acme Corporation** totalling **$1,740.00** was detected in Odoo in Draft/Quotation state. The quotation is approximately 32 days old (dated 2026-01-16) and has not been confirmed, invoiced, or followed up on.

## Urgency: MEDIUM
The quotation is not overdue in a financial sense, but its age (~32 days without confirmation) puts it at risk of being lost. A named customer with a $1,740 deal warrants timely follow-up to avoid pipeline staleness.

## Recommended Actions
- **Follow up with Acme Corporation**: Contact the customer to ask whether they wish to confirm quotation S00001 ($1,740.00 total).
- **Check with Marc Demo** (assigned salesperson): Confirm whether this deal is still active or if it was verbally closed/cancelled without being updated in Odoo.
- **Confirm the order in Odoo** (if customer approves): Sales > Orders > Quotations > S00001 > Click "Confirm Order"
- **Cancel the quotation in Odoo** (if deal is dead): Sales > Orders > Quotations > S00001 > Action > Cancel — to keep the pipeline accurate.
- **Add an internal note** to S00001 documenting the follow-up outcome.

## Context
- Order Date: 2026-01-16 (32 days ago as of 2026-02-17)
- Assigned To: Marc Demo
- Invoice Status: None (no revenue recognized)
- No source/origin recorded — unclear how this lead was generated
- No internal notes on the record
- This is the oldest quotation in the detected batch; the age alone is a signal it may have been overlooked
