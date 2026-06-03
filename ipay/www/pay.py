import frappe

from ipay.ipay.main.utils.ipay_redirect import resolve_pay_token


def get_context(context):
    context.no_cache = 1
    token = frappe.form_dict.get("token")
    request_name, status = resolve_pay_token(token)

    if not request_name:
        context.invalid = True
        context.expired = status == "expired"
        return

    req = frappe.db.get_value(
        "iPay Request", request_name, ["sales_invoice", "status"], as_dict=True
    )
    outstanding = frappe.db.get_value(
        "Sales Invoice", req.sales_invoice, "outstanding_amount"
    )

    context.token = token
    context.invoice = req.sales_invoice
    context.amount = frappe.utils.flt(outstanding)
    context.paid = req.status == "Success"
    context.enable_redirect = frappe.db.get_single_value(
        "iPay Settings", "enable_redirect"
    )
