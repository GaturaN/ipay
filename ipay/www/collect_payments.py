import frappe

# Roles allowed to use the collection page.
ALLOWED_ROLES = {"System Manager", "iPay Manager", "iPay User"}


def get_context(context):
    context.no_cache = 1

    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/collect_payments"
        raise frappe.Redirect

    if not (ALLOWED_ROLES & set(frappe.get_roles())):
        frappe.throw("You are not permitted to collect payments.", frappe.PermissionError)

    context.invoices = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]},
        fields=["name", "customer_name", "outstanding_amount", "posting_date"],
        order_by="posting_date desc",
        limit_page_length=50,
    )
