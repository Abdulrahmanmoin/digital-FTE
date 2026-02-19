---
type: odoo_action
odoo_model: "sale.order"
record_id: "16"
record_name: "S00016"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00016.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00016

## Summary
Sales Order S00016 for Gemini Furniture ($1,186.50) was confirmed on 2026-02-16 and is assigned to Marc Demo. No delivery has been scheduled and no invoice has been created yet.

## Urgency: MEDIUM
Order is confirmed and in the fulfillment queue. Delivery scheduling and invoicing are the immediate next steps — no emergency, but delays will slow down cash collection.

## Recommended Actions
- Verify delivery scheduling: Odoo → Sales → Orders → S00016 → Delivery tab — confirm a delivery order exists with a scheduled date.
- If delivery is not yet scheduled, notify Marc Demo (assigned salesperson) to coordinate with warehouse/logistics.
- Once goods are dispatched, create the invoice: S00016 → Create Invoice → Invoice Gemini Furniture for $1,186.50.
- Add any special handling notes from Gemini Furniture to the order before picking begins.

## Context
- Invoice status is currently `no` — expected at this stage, but must be resolved post-shipment to avoid payment delays.
- No source/origin on the order — likely a manual entry; verify no duplicate or related opportunity exists in CRM.
- Assigned salesperson: Marc Demo. Escalation not required at this amount, but follow up if delivery is not scheduled within 1 business day.
