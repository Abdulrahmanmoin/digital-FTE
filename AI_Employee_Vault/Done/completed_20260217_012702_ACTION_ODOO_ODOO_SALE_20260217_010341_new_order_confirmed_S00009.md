---
type: odoo_action
odoo_model: "sale.order"
record_id: "9"
record_name: "S00009"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00009.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00009

## Summary
Sales order S00009 for Gemini Furniture ($654.00) was confirmed 8 days ago (2026-02-09) and is assigned to Marc Demo, but no invoice has been created yet. Immediate invoicing and delivery verification are needed.

## Urgency: MEDIUM
Order is confirmed and 8 days old with invoice status "no" — billing has not been initiated, creating a cash flow delay. Not yet overdue, but requires prompt action today.

## Recommended Actions
- Create invoice in Odoo: Sales > Orders > S00009 > Create Invoice — bill Gemini Furniture for $654.00
- Verify delivery order: check that a delivery/shipment has been scheduled for S00009
- Send order confirmation to Gemini Furniture if not already done
- Notify Marc Demo (assigned salesperson) to close out the invoicing step

## Context
- Order Date: 2026-02-09 (8 days ago as of 2026-02-17)
- Assigned To: Marc Demo
- Invoice Status: "no" (no invoice exists yet)
- No internal notes or source/origin recorded on the order
- Amount ($654.00) is within normal range — no escalation required, but prompt billing is best practice
