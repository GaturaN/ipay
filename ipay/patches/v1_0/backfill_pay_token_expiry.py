import frappe


def execute():
    """Give existing payment links an expiry so the new TTL policy is uniform.
    Only unpaid requests with a token and no expiry yet."""
    ttl_days = frappe.utils.cint(
        frappe.db.get_single_value("iPay Settings", "payment_link_ttl_days")
    ) or 7
    expiry = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=ttl_days)

    names = frappe.get_all(
        "iPay Request",
        filters={
            "pay_token": ["is", "set"],
            "pay_token_expiry": ["is", "not set"],
            "status": ["not in", ["Success", "Overpaid"]],
        },
        pluck="name",
    )
    for name in names:
        frappe.db.set_value(
            "iPay Request", name, "pay_token_expiry", expiry, update_modified=False
        )
