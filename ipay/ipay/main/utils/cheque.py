"""Which invoices a collected cheque already covers.

A cheque is recorded as a DRAFT Payment Entry for the accounts team to submit, and a draft does
not reduce outstanding — so the invoice still looks unpaid to every other query. This answers
"is this money already in hand" once, for the marker on a card and the guard on a bundle.
"""

import frappe
from frappe.utils import flt

from ipay.ipay.main.utils.constants import CHEQUE_MODE


def awaiting_cheque_amounts(sales_invoices):
    """Map of Sales Invoice -> amount a draft cheque covers (two batched queries)."""
    names = [name for name in (sales_invoices or []) if name]
    if not names:
        return {}

    rows = frappe.get_all(
        "Payment Entry Reference",
        filters={"reference_doctype": "Sales Invoice", "reference_name": ["in", names], "docstatus": 0},
        fields=["parent", "reference_name", "allocated_amount"],
    )
    if not rows:
        return {}

    # A draft reference alone is not a cheque — only the parent entry knows the mode.
    cheques = set(
        frappe.get_all(
            "Payment Entry",
            filters={
                "name": ["in", list({row.parent for row in rows})],
                "docstatus": 0,
                "mode_of_payment": CHEQUE_MODE,
            },
            pluck="name",
        )
    )

    covered = {}
    for row in rows:
        if row.parent in cheques:
            covered[row.reference_name] = covered.get(row.reference_name, 0) + flt(row.allocated_amount)
    return covered
