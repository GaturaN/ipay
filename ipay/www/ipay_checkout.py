import frappe

from ipay.ipay.main.utils.ipay_redirect import build_checkout_form


def get_context(context):
    context.no_cache = 1
    request_name = frappe.form_dict.get("request")
    settings = frappe.get_single("iPay Settings")

    if not settings.enable_redirect:
        context.disabled = True
        return

    if not request_name or not frappe.db.exists("iPay Request", request_name):
        context.not_found = True
        return

    action, fields = build_checkout_form(request_name, frappe.form_dict.get("phone"))

    # iPay requires a telephone number; if none was supplied or on file, ask for one.
    if not fields.get("tel"):
        context.phone_required = True
        context.request_name = request_name
        return

    context.action = action
    context.fields = fields
