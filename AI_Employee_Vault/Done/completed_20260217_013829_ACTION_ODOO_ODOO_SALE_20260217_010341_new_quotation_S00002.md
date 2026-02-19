---
type: odoo_action
odoo_model: "sale.order"
record_id: "2"
record_name: "S00002"
event_type: "new_quotation"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_quotation_S00002.md"
status: pending_approval
---

# Odoo Event: new_quotation — S00002

## Summary
Quotation S00002 for customer **Ready Mat** ($2,947.50) was detected in draft/Quotation state. It was created on 2026-01-16 and has been sitting unconfirmed for **32 days** with no invoicing activity and no recorded follow-up.

## Urgency: MEDIUM
A month-old unconfirmed quotation poses a revenue risk — the customer may have lost interest or purchased elsewhere. Prompt follow-up is needed to either convert this to a confirmed sale or close the opportunity.

## Recommended Actions
- **Follow up with Ready Mat** — Contact the customer to confirm their interest, clarify any questions about the quotation, or determine if the deal is lost.
- **Confirm the sale order in Odoo** (if customer agrees): Sales > Quotations > S00002 > Click "Confirm"
- **Cancel/mark as lost** (if deal is dead): Sales > Quotations > S00002 > Action > Cancel — to keep pipeline data clean.
- **Review pricing validity** — Verify that the products and prices quoted on 2026-01-16 are still accurate (stock, pricing changes over 32 days).
- **Log a follow-up note** in Odoo's chatter on S00002 to record the contact attempt and outcome.
- **Assign a follow-up deadline** — If Mitchell Admin is the responsible salesperson, ensure they are aware this quotation is stale.

## Context
- Assigned salesperson: Mitchell Admin
- Order date: 2026-01-16 (32 days ago)
- Invoice status: none (no invoice generated yet)
- No source/origin recorded — may indicate a manually created quotation without a linked CRM opportunity, which is a pipeline tracking gap worth addressing.
- Amount ($2,947.50) is moderate — not a high-value escalation threshold, but worth recovering if possible.
