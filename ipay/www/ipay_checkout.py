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
    entered_email = frappe.form_dict.get("email")
    action, fields = build_checkout_form(request_name, entered_phone, entered_email)

    # iPay requires a telephone number; if none was supplied or on file, ask for
    # one. Phone is asked first; the email step carries the entered phone forward
    # so a customer who supplies both in turn does not lose the first.
    if not fields.get("tel"):
        context.phone_required = True
        context.token = token
        context.email = entered_email or ""
        return

    # Persist any operator-entered contact to the Customer (blanks only) so future
    # requests are pre-filled — matching the STK/desk paths. Guests never write
    # the Customer master. Best-effort: never block checkout on a save failure.
    # Done before the email gate so a just-entered phone is saved even when we
    # still need to collect the email.
    if frappe.session.user != "Guest" and (entered_phone or entered_email):
        try:
            save_customer_contact(request_name, phone=entered_phone, email=entered_email)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()

    # iPay also requires an email (for the receipt / card auth); if none was
    # supplied or on file, ask for one — mirroring the phone prompt above.
    if not fields.get("eml"):
        context.email_required = True
        context.token = token
        context.phone = entered_phone or ""
        return

    context.action = action
    context.fields = fields
