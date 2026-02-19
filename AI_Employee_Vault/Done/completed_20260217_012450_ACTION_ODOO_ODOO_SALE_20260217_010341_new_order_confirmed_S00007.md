---
type: odoo_action
odoo_model: "sale.order"
record_id: "7"
record_name: "S00007"
event_type: "new_order_confirmed"
urgency: "medium"
source_task: "ODOO_SALE_20260217_010341_new_order_confirmed_S00007.md"
status: pending_approval
---

# Odoo Event: new_order_confirmed — S00007

## Summary
Sales order S00007 for customer Gemini Furniture has been confirmed with a total of $1,706.00. The invoice status is currently "to invoice", meaning an invoice must still be created to initiate payment collection.

## Urgency: MEDIUM
Order is confirmed but not yet invoiced. Prompt invoicing is needed to avoid payment delays. No overdue risk at this stage, but action should be taken within the business day.

## Recommended Actions
- Create invoice in Odoo: Sales > Orders > S00007 > "Create Invoice" button
- Verify delivery is scheduled: Inventory > Transfers — check for linked delivery order for S00007
- Send order confirmation or proforma invoice to Gemini Furniture if not already done
- Notify assigned salesperson Mitchell Admin that invoicing is pending

## Context
- Order Date: 2026-02-16 17:18:18
- Customer: Gemini Furniture
- Amount: $1,706.00
- Assigned To: Mitchell Admin
- Invoice Status: to invoice (no invoice raised yet)
- No internal notes or special origin/source on the order
