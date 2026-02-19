---
type: odoo_action
odoo_model: "sale.order"
record_id: "11"
record_name: "S00011"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00011.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00011

## Summary
Sales Order S00011 for **Gemini Furniture** ($1,096.50) has been confirmed but has no invoice raised yet, 22 days after the order date. Delivery and billing follow-up are required.

## Urgency: MEDIUM
Order is confirmed but unbilled 22 days after placement. No delivery confirmation available. Risk of cash flow delay if not actioned promptly.

## Recommended Actions
- Check delivery status in Odoo: Sales > Orders > S00011 > Delivery smart button — verify shipment status or schedule delivery if not yet done.
- Create invoice for Gemini Furniture: open S00011 > click "Create Invoice" > review line items > Confirm > Send to customer.
- Contact Marc Demo (assigned salesperson) to confirm no hold or special terms apply to this order.
- If delivery is already complete, escalate invoice creation as high priority to avoid further billing delay.

## Context
- Order Date: 2026-01-26 (22 days ago)
- Invoice Status: `no` — no invoice has been generated
- Assigned Salesperson: Marc Demo
- No internal notes or special origin/source recorded on the order
- This record was newly detected by the Odoo watcher; confirm in Odoo whether delivery smart button shows any pending transfers
