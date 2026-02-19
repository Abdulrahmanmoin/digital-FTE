---
type: odoo_action
odoo_model: "sale.order"
record_id: "4"
record_name: "S00004"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00004.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00004

## Summary
Sales order S00004 for customer Gemini Furniture has been confirmed with a total value of $2,240.00. No invoice has been created yet and delivery has not been scheduled.

## Urgency: MEDIUM
Order is confirmed and billable but has no invoice raised yet. Prompt action is needed to initiate invoicing and delivery to avoid delays in revenue recognition and customer fulfilment.

## Recommended Actions
- Create invoice in Odoo: Sales > Orders > S00004 > Create Invoice — confirm and send to Gemini Furniture
- Verify delivery order was created and schedule shipment with warehouse team
- Send order confirmation or proforma invoice to Gemini Furniture if not already done
- Confirm order line items and pricing with Mitchell Admin before invoicing

## Context
- Customer: Gemini Furniture
- Order Amount: $2,240.00
- Order Date: 2026-02-16
- Assigned To: Mitchell Admin
- Invoice Status: none (no invoice created)
- No internal notes or source/origin recorded on the order
- No previous state — this was a newly detected confirmed order
