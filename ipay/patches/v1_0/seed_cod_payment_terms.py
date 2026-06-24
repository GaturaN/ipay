import frappe


def execute():
    """Seed the "Cash on Delivery" Payment Terms Template (and its Payment Term)
    that the COD auto-create flow keys on.

    cod_create_request only raises an iPay Request when a customer's
    payment_terms == "Cash on Delivery" (a Payment Terms Template). ERPNext ships
    that template only in its test fixtures, not on install, so on a fresh site it
    would never exist and the COD feature would silently do nothing. Create it
    here (idempotently) to match the live configuration. No-op where it already
    exists, so it never clobbers a site's own template."""
    if not frappe.db.exists("Payment Term", "Cash on Delivery"):
        frappe.get_doc(
            {
                "doctype": "Payment Term",
                "payment_term_name": "Cash on Delivery",
                "invoice_portion": 100,
                "due_date_based_on": "Day(s) after invoice date",
                "credit_days": 0,
                "credit_months": 0,
            }
        ).insert(ignore_permissions=True)

    if not frappe.db.exists("Payment Terms Template", "Cash on Delivery"):
        frappe.get_doc(
            {
                "doctype": "Payment Terms Template",
                "template_name": "Cash on Delivery",
                "allocate_payment_based_on_payment_terms": 1,
                "terms": [
                    {
                        "doctype": "Payment Terms Template Detail",
                        "payment_term": "Cash on Delivery",
                        "invoice_portion": 100,
                        "due_date_based_on": "Day(s) after invoice date",
                        "credit_days": 0,
                        "credit_months": 0,
                    }
                ],
            }
        ).insert(ignore_permissions=True)
