import frappe


def execute():
    """Default the Collect app's payment-term filter to Cash on Delivery + End of Day
    — the terms drivers settle on delivery. Idempotent: seeds only when the setting is
    empty, so it never overrides an admin's own choice, and skips a template that does
    not exist on the site."""
    settings = frappe.get_single("iPay Settings")
    if settings.get("collect_payment_terms"):
        return
    for template in ("Cash on Delivery", "End of Day"):
        if frappe.db.exists("Payment Terms Template", template):
            settings.append("collect_payment_terms", {"payment_terms_template": template})
    if settings.get("collect_payment_terms"):
        # A site may not have filled in credentials yet; seeding must not trip the
        # single's mandatory-field validation and abort the migrate.
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
