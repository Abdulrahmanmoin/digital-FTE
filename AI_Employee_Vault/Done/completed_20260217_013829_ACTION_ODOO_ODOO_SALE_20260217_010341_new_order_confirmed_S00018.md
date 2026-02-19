---
type: odoo_action
odoo_model: "sale.order"
record_id: "18"
record_name: "S00018"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00018.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00018

## Summary
Sales Order S00018 for **Gemini Furniture** ($831.00) has been confirmed but has no invoice created yet. The order date is 2026-01-12, making it over 35 days old with no invoicing action taken.

## Urgency: MEDIUM
Order is confirmed and assigned (Marc Demo) but invoice status is "no" — invoicing is overdue for a month-old confirmed order. No collections risk yet, but delay should be addressed promptly.

## Recommended Actions
- Verify delivery status in Odoo: Sales > Orders > S00018 > check Delivery smart button
- If delivery is complete, create the invoice: S00018 > Create Invoice
- If delivery is not yet scheduled, confirm scheduling with Marc Demo
- Send order confirmation or proforma invoice to Gemini Furniture if not already sent
- Review internally why no invoice has been raised 35+ days after the order date

## Context
- Assigned salesperson: Marc Demo
- Order date: 2026-01-12 (detected by watcher: 2026-02-17)
- Invoice status field shows "no" — no invoice object linked to this order
- No internal notes or origin/source recorded on the order
- Amount ($831.00) is moderate — routine follow-up, not escalation-level
