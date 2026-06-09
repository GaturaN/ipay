import frappe

from ipay.ipay.main.utils.ipay_redirect import build_checkout_form, _request_from_token


def get_context(context):
    context.no_cache = 1
    token = frappe.form_dict.get("token")
    settings = frappe.get_single("iPay Settings")

    if not settings.enable_redirect:
        context.disabled = True
        return

    request_name = _request_from_token(token)
    if not request_name:
        context.not_found = True
        return

    action, fields = build_checkout_form(request_name, frappe.form_dict.get("phone"))

    # iPay requires a telephone number; if none was supplied or on file, ask for one.
    if not fields.get("tel"):
        context.phone_required = True
        context.token = token
        return

    context.action = action
    context.fields = fields
