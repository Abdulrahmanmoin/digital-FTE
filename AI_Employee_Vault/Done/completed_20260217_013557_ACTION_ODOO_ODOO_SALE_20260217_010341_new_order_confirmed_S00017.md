---
type: odoo_action
odoo_model: "sale.order"
record_id: "17"
record_name: "S00017"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00017.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00017

## Summary
Sales order S00017 for **Gemini Furniture** ($951.00) has been confirmed, but no invoice has been created. The order was placed on 2026-01-19 (~4 weeks ago), and invoicing is still outstanding.

## Urgency: MEDIUM
No invoice has been issued on a confirmed order that is ~4 weeks old. Revenue cannot be collected until an invoice is created and sent. Delivery status is also unconfirmed.

## Recommended Actions
- Create invoice in Odoo: Sales > Orders > S00017 > **Create Invoice**, then confirm and send to Gemini Furniture
- Verify delivery order exists and is scheduled: Inventory > Transfers > filter by S00017
- Notify assigned salesperson **Marc Demo** that invoicing is pending on his order
- Investigate why a January 19 order was not invoiced until now — check for process gap or data sync delay

## Context
- Customer: Gemini Furniture
- Order Amount: $951.00
- Assigned To: Marc Demo
- Order Date: 2026-01-19 (detected 2026-02-17 — ~29 day gap)
- Invoice Status: none ("no") — no invoice raised yet
- No internal notes or source/origin recorded on the order
- Delivery status unknown — confirm fulfillment before or alongside invoicing
