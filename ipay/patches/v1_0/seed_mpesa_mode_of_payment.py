import frappe


def execute():
    """Seed the "MPESA" Mode of Payment that make_payment_entry writes on every
    iPay Payment Entry (make_payment_entry.py hardcodes mode_of_payment="MPESA").

    Replaces the old broad `fixtures = ["Mode of Payment"]` export, which
    re-imported every mode of payment on each migrate and could overwrite a
    site's own Mode-of-Payment-to-account mappings. Idempotent and account-free
    (the receiving account is resolved per-company at Payment Entry time, not
    from the mode), so it never clobbers a site's configuration."""
    if not frappe.db.exists("Mode of Payment", "MPESA"):
        frappe.get_doc(
            {
                "doctype": "Mode of Payment",
                "mode_of_payment": "MPESA",
                "type": "Cash",
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
