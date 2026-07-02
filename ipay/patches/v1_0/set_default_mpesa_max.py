import frappe


def execute():
    """Seed the M-Pesa ceiling to 250,000 on existing sites — the field default only
    applies to fresh installs, so without this the cap reads 0 (disabled) after migrate.
    Idempotent and non-destructive: only sets it when unset, never overriding an admin's
    own value (including a deliberate 0 = no cap, once they've set it)."""
    if not frappe.db.get_single_value("iPay Settings", "mpesa_max_amount"):
        frappe.db.set_single_value("iPay Settings", "mpesa_max_amount", 250000)
