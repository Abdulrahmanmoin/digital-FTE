---
type: odoo_action
odoo_model: "sale.order"
record_id: "20"
record_name: "S00020"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00020.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed → S00020

## Summary
Sales Order S00020 for customer **YourCompany, Joel Willis** (total: **$2,947.50**) was confirmed approximately 32 days ago on 2026-01-16 but has never been invoiced — invoice status is currently `no`.

## Urgency: MEDIUM
Order has been confirmed for ~32 days with no invoice raised, indicating a potentially stalled workflow. Revenue is unrealized and cash has not been collected. Escalate to HIGH if delivery was already completed without triggering an invoice.

## Recommended Actions
- **Check delivery status**: Odoo > Sales > Orders > S00020 > Delivery tab — confirm whether goods/services have been shipped or fulfilled.
- **If delivered**: Raise invoice immediately — Sales > S00020 > Create Invoice > Confirm.
- **If not delivered**: Contact assigned salesperson (Mitchell Admin) to determine why a 2026-01-16 order is still unfulfilled.
- **Add internal note** on S00020 in Odoo documenting current status and next steps.
- **Verify customer**: "YourCompany" may indicate a demo/internal record — confirm this is a real customer transaction before invoicing.

## Context
- Order date: 2026-01-16 (32 days ago as of 2026-02-17)
- No source/origin field populated and no internal comments on the order.
- Assigned to: Mitchell Admin — this person should be the first point of contact for status.
- No action should be taken in Odoo by the AI system; all steps above are for human execution.
