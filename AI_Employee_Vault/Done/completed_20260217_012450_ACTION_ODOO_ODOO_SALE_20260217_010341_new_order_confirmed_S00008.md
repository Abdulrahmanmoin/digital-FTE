---
type: odoo_action
odoo_model: "sale.order"
record_id: "8"
record_name: "S00008"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00008.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00008

## Summary
Sales Order S00008 for customer **Gemini Furniture** was confirmed on 2026-02-16, totalling **$462.00** and assigned to Marc Demo. No invoice has been created yet and no delivery has been scheduled.

## Urgency: MEDIUM
Order is confirmed and customer-facing, but not overdue. Prompt invoicing and delivery scheduling are required to complete the order fulfilment cycle.

## Recommended Actions
- Check delivery scheduling: Sales > Orders > S00008 — verify if a Delivery Order (DO) exists and has a scheduled date
- Create invoice: Open S00008 in Odoo > click "Create Invoice" — invoice status is currently `no`
- Send invoice to Gemini Furniture once created
- Notify or follow up with assigned salesperson Marc Demo to ensure fulfilment is on track
- Optionally confirm delivery timeline with Gemini Furniture if not yet communicated

## Context
- Order date: 2026-02-16 17:18:18
- Amount: $462.00 (moderate — no escalation required)
- No source/origin recorded; no internal notes
- Invoice status `no` is the primary gap — this order will not generate revenue until invoiced and paid
- No previous state — this was a newly detected confirmed order (may have been confirmed directly, skipping quotation stage)
