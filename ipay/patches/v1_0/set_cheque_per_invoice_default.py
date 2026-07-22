import frappe


def execute():
    """Cheque Per Invoice defaults on, but a Check field reads 0 when unset on an existing single,
    so per-invoice cheques would silently turn off after migrate. Seed it to 1 (mirrors
    set_default_mpesa_max). One-time, so a later admin choice of off is preserved."""
    if not frappe.db.get_single_value("iPay Settings", "cheque_per_invoice"):
        frappe.db.set_single_value("iPay Settings", "cheque_per_invoice", 1)
