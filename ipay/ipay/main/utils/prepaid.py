"""Detect prepaid invoices so iPay never raises a payment request for them.

A prepaid order is settled automatically by the wave_sync_hypa app (it creates
the Payment Entry on Sales Invoice submit), so an iPay request, link or prompt
for such an invoice is redundant and confusing. "Prepaid" is authoritative on
the Sales Order via the wave_sync custom field `wave_payment_classification`.

This replicates wave_sync's SI -> Sales Order trace with a couple of cheap
reads rather than importing wave_sync (which already imports ipay — importing
back would be circular). It degrades to "not prepaid" when the custom field is
absent, so the iPay app still works standalone.
"""

import frappe

PREPAID_CLASSIFICATION = "prepaid"


def is_sales_invoice_prepaid(sales_invoice):
    """True when any Sales Order behind this Sales Invoice is classified prepaid."""
    if not sales_invoice:
        return False
    if not frappe.get_meta("Sales Order").has_field("wave_payment_classification"):
        return False

    sales_orders = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": sales_invoice, "sales_order": ["is", "set"]},
        pluck="sales_order",
        distinct=True,
    )
    for so in set(sales_orders):
        classification = frappe.db.get_value("Sales Order", so, "wave_payment_classification")
        if (classification or "").strip() == PREPAID_CLASSIFICATION:
            return True
    return False


def prepaid_invoice_names(sales_invoices):
    """Subset of the given Sales Invoices that are prepaid (two batched queries).

    Use this instead of calling is_sales_invoice_prepaid in a loop when checking
    many invoices at once (e.g. the collection page list)."""
    names = [n for n in (sales_invoices or []) if n]
    if not names or not frappe.get_meta("Sales Order").has_field("wave_payment_classification"):
        return set()

    items = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": ["in", names], "sales_order": ["is", "set"]},
        fields=["parent", "sales_order"],
    )
    sales_orders = {it.sales_order for it in items}
    if not sales_orders:
        return set()

    prepaid_orders = set(frappe.get_all(
        "Sales Order",
        filters={"name": ["in", list(sales_orders)], "wave_payment_classification": PREPAID_CLASSIFICATION},
        pluck="name",
    ))
    return {it.parent for it in items if it.sales_order in prepaid_orders}
