---
type: odoo_action
odoo_model: "sale.order"
record_id: "12"
record_name: "S00012"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00012.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00012

## Summary
Sales order S00012 for customer **Gemini Furniture** ($556.00) has been confirmed and is assigned to Marc Demo. No invoice has been created yet and no delivery has been recorded.

## Urgency: MEDIUM
Order is confirmed and awaiting fulfillment. No payment is overdue, but the invoicing and delivery steps have not been initiated, which risks stalling the order.

## Recommended Actions
- **Check delivery**: Go to Odoo Inventory → Transfers and verify a delivery order (WH/OUT) exists for S00012. If not, create and validate it.
- **Create invoice**: Open S00012 in Odoo Sales → click "Create Invoice" → confirm and email the invoice to Gemini Furniture.
- **Notify salesperson**: Inform Marc Demo (assigned salesperson) that S00012 is confirmed and pending delivery/invoicing steps.

## Context
- Customer: Gemini Furniture
- Order total: $556.00
- Invoice status at time of detection: `no` (no invoice created)
- Order date: 2026-02-16
- No internal notes or special source/origin on the order.
- This is a routine fulfillment follow-up; no escalation required unless delivery or payment is delayed further.
