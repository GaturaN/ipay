import frappe

from ipay.ipay.main.utils.ipay_redirect import (
    build_checkout_form,
    resolve_pay_token,
    save_customer_contact,
)


def get_context(context):
    context.no_cache = 1
    token = frappe.form_dict.get("token")
    settings = frappe.get_single("iPay Settings")

    if not settings.enable_redirect:
        context.disabled = True
        return

    request_name, status = resolve_pay_token(token)
    if not request_name:
        context.not_found = True
        context.expired = status == "expired"
        return

    entered_phone = frappe.form_dict.get("phone")
    action, fields = build_checkout_form(request_name, entered_phone)

    # iPay requires a telephone number; if none was supplied or on file, ask for one.
    if not fields.get("tel"):
        context.phone_required = True
        context.token = token
        return

    # Persist an operator-entered number to the Customer (blanks only) so future
    # requests are pre-filled — matching the STK/desk paths. Guests never write
    # the Customer master. Best-effort: never block checkout on a save failure.
    if entered_phone and frappe.session.user != "Guest":
        try:
            save_customer_contact(request_name, phone=entered_phone)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()

    context.action = action
    context.fields = fields
