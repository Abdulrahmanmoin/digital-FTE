---
type: odoo_action
odoo_model: "account.move"
record_id: "12"
record_name: "RINV/2026/00001"
event_type: "invoice_overdue"
urgency: "high"
source_task: "ODOO_INV_20260217_010341_invoice_overdue_RINV_2026_00001.md"
status: pending_approval
---

# Odoo Event: invoice_overdue — RINV/2026/00001

## Summary
A customer credit note of **11,750.00** issued to **Azure Interior** became overdue on 2026-02-14 and has not been paid or applied. The business owes this credit to the customer — it is not a receivable.

## Urgency: HIGH
This is an obligation owed to a named customer (Azure Interior) that is 3 days past due. The amount is material and the record has no internal notes or assigned human owner, indicating it may have been overlooked.

## Recommended Actions
- **Verify source**: Identify why RINV/2026/00001 was issued (return, overbilling, service failure) — no origin is recorded on the document.
- **Apply to open invoice (preferred)**: If Azure Interior has any open invoices, reconcile this credit note against them in Odoo: Accounting > Customers > Credit Notes > RINV/2026/00001 > Add Outstanding Credit.
- **Issue refund (if no open invoice)**: If no open invoice exists, register a payment (refund) to Azure Interior: Accounting > Customers > Credit Notes > RINV/2026/00001 > Register Payment.
- **Reassign record**: Currently assigned to OdooBot. Assign RINV/2026/00001 to the appropriate account manager.
- **Notify Azure Interior**: Inform the customer that their credit of 11,750.00 is being processed, and provide an expected settlement date.

## Context
- Document type is `out_refund` (Customer Credit Note) — this is money owed **by the business to the customer**, not the other way around.
- Due date was 2026-02-14; today is 2026-02-17, making it 3 days overdue.
- No source/origin document is linked, so the reason for the credit note must be investigated manually.
- Assigned to OdooBot, suggesting no human has taken ownership of this record.
- No payment plan or internal notes exist on the record.
