---
type: odoo_action
odoo_model: "sale.order"
record_id: "5"
record_name: "S00005"
event_type: "new_quotation"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_quotation_S00005.md"
status: pending_approval
---

# Odoo Event: new_quotation — S00005

## Summary
Quotation S00005 for **Acme Corporation** ($405.00) has been detected in draft state. The quotation was created on 2026-01-16 and has been unconfirmed for over 30 days, assigned to Marc Demo.

## Urgency: MEDIUM
This is a stale quotation — 30+ days in draft with no confirmation or internal notes. Risk of losing the deal without follow-up, though there is no immediate financial urgency (no overdue invoice, no blocked delivery).

## Recommended Actions
- **Follow up with Acme Corporation**: Marc Demo should contact the customer to check if they want to proceed with the quotation.
- **Confirm the order in Odoo** if the customer agrees: Sales > Orders > Quotations > S00005 > Confirm.
- **Send a quotation reminder** email to the customer if no recent contact has been made.
- **Cancel S00005 in Odoo** if the deal is no longer active, to keep the sales pipeline clean.
- **Add a chatter note** to S00005 documenting any follow-up action taken.

## Context
- Customer: Acme Corporation
- Amount: $405.00 (modest value — standard pipeline hygiene applies)
- Assigned Salesperson: Marc Demo
- Order Date: 2026-01-16 (32 days ago as of 2026-02-17)
- Invoice Status: none (no delivery or invoice generated — consistent with draft state)
- No source/origin on the record — appears to be a manually created quotation, not a web lead.
- No internal notes or comments recorded in Odoo at time of detection.
