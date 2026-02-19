---
type: odoo_action
odoo_model: "sale.order"
record_id: "15"
record_name: "S00015"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00015.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00015

## Summary
Sales Order S00015 for **Gemini Furniture** was confirmed with a total of **$1,541.50**, but no invoice has been created yet. The order is 15 days old (placed 2026-02-02) and is assigned to Marc Demo.

## Urgency: MEDIUM
Order is confirmed and revenue is committed, but the invoicing step has not been completed. A 15-day gap between order date and current date without an invoice raises a follow-up need, though no payment is overdue yet.

## Recommended Actions
- **Create Invoice in Odoo**: Sales > Orders > S00015 > Create Invoice (amount: $1,541.50)
- **Check delivery status**: Verify a delivery order exists and is scheduled for Gemini Furniture
- **Notify Marc Demo**: Confirm he has sent order confirmation to the customer and is tracking delivery
- **Send proforma/order confirmation to Gemini Furniture** if not already done

## Context
- Order date: 2026-02-02 — 15 days elapsed without invoicing
- Invoice status: `no` (no invoice created at all)
- Assigned salesperson: Marc Demo
- No internal notes or special handling flags on this order
- Amount ($1,541.50) is moderate; not a threshold escalation, but warrants prompt invoicing to maintain cash flow
