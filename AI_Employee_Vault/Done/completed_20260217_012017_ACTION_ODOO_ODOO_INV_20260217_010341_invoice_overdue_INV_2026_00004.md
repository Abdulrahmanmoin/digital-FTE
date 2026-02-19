---
type: odoo_action
odoo_model: "account.move"
record_id: "4"
record_name: "INV/2026/00004"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_INV_2026_00004.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — INV/2026/00004

## Summary
Customer invoice INV/2026/00004 for Acme Corporation totalling $31,750.00 is 18 days overdue (due date: 2026-01-30) with no payment received. Immediate follow-up is required to recover this receivable.

## Urgency: HIGH
$31,750.00 outstanding from a commercial customer, 18 days past due with no partial payment. Risk of bad debt increases significantly without prompt action.

## Recommended Actions
- Send a payment reminder to Acme Corporation referencing INV/2026/00004, amount $31,750.00, and due date 2026-01-30. Request payment ETA or confirmation the invoice was received.
- Notify Marc Demo (assigned to this invoice) that it is now overdue and action is needed.
- Check Odoo and email for any open disputes or credit note requests from Acme Corporation before escalating.
- Register payment in Odoo once funds are received: Accounting > Customers > Invoices > INV/2026/00004 > Register Payment
- If no response by 2026-02-20 (3 business days), escalate to management and initiate formal collection procedures.

## Context
- Invoice date and due date are both 2026-01-30 — the invoice was issued with immediate payment terms (net 0 days or due on issue).
- No source/origin (sales order) is linked, so there is no automated escalation chain.
- The full $31,750.00 remains unpaid — no partial payments have been recorded.
- Last write date on the Odoo record: 2026-02-16, suggesting it may have been recently reviewed but no payment registered.
