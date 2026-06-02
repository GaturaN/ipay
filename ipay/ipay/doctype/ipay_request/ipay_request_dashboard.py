from frappe import _


def get_data():
    return {
        "fieldname": "ipay_request",
        "internal_links": {
            "Sales Invoice": ["sales_invoice"],
            "Payment Entry": ["payment_entry"],
            "Driver": ["driver"],
        },
        "transactions": [
            {"label": _("Payment"), "items": ["Payment Entry"]},
            {"label": _("References"), "items": ["Sales Invoice", "Driver"]},
        ],
    }
