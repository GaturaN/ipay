import frappe
from frappe.utils import flt

# Payments that came in wrong and need a human: an Underpaid balance still to chase,
# or an Overpaid excess sitting as customer credit to apply or refund.
ATTENTION_STATUSES = ["Underpaid", "Overpaid"]


def execute(filters=None):
    columns = [
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": "Request", "fieldname": "request", "fieldtype": "Link", "options": "iPay Request", "width": 170},
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
        {"label": "Invoice", "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
        {"label": "Expected", "fieldname": "expected", "fieldtype": "Currency", "width": 110},
        {"label": "Received", "fieldname": "received", "fieldtype": "Currency", "width": 110},
        {"label": "Difference", "fieldname": "difference", "fieldtype": "Currency", "width": 110},
        {"label": "Payment Entry", "fieldname": "payment_entry", "fieldtype": "Link", "options": "Payment Entry", "width": 160},
        {"label": "When", "fieldname": "when", "fieldtype": "Datetime", "width": 160},
        {"label": "Detail", "fieldname": "detail", "fieldtype": "Data", "width": 320},
    ]

    rows = frappe.get_all(
        "iPay Request",
        filters={"status": ["in", ATTENTION_STATUSES], "docstatus": 1},
        fields=["name", "status", "customer", "sales_invoice", "amount", "payment_entry", "result_detail", "modified"],
        order_by="modified desc",
    )

    data = []
    for r in rows:
        # Received is the actual money booked; Expected is what was charged. The
        # difference tells the accountant how much to chase (Underpaid) or credit (Overpaid).
        received = flt(frappe.db.get_value("Payment Entry", r.payment_entry, "paid_amount")) if r.payment_entry else 0
        expected = flt(r.amount)
        data.append({
            "status": r.status,
            "request": r.name,
            "customer": r.customer,
            "invoice": r.sales_invoice,
            "expected": expected,
            "received": received,
            "difference": received - expected,
            "payment_entry": r.payment_entry,
            "when": r.modified,
            "detail": r.result_detail,
        })

    return columns, data
