import frappe

from ipay.ipay.main.utils.ipay_redirect import _mpesa_max_amount, resolve_pay_token
from ipay.www.collect_payments import ALLOWED_ROLES


def get_context(context):
    context.no_cache = 1
    context.favicon = "/assets/ipay/manifest/favicon-196.png"  # iPay Collect tab icon
    token = frappe.form_dict.get("token")
    request_name, status = resolve_pay_token(token)

    if not request_name:
        context.invalid = True
        context.expired = status == "expired"
        context.held = status == "held"
        return

    req = frappe.db.get_value(
        "iPay Request", request_name, ["sales_invoice", "amount", "status"], as_dict=True
    )

    # Every invoice the link collects, each with its live outstanding, so the payer
    # sees the whole bundle broken down — not just the primary. A single request
    # has no child rows, so fall back to its one invoice.
    member_names = [
        inv
        for inv in frappe.get_all(
            "iPay Request Invoice", filters={"parent": request_name}, pluck="sales_invoice"
        )
        if inv
    ] or [req.sales_invoice]
    context.token = token
    context.invoice = req.sales_invoice
    context.invoices = [
        {
            "name": name,
            "amount": frappe.utils.flt(
                frappe.db.get_value("Sales Invoice", name, "outstanding_amount")
            ),
        }
        for name in member_names
    ]
    # The total matches what the STK actually charges (the live sum of the
    # members' outstanding); fall back to the stored amount if all read zero.
    context.amount = sum(inv["amount"] for inv in context.invoices) or frappe.utils.flt(
        req.amount
    )
    context.paid = req.status == "Success"
    context.enable_redirect = frappe.db.get_single_value(
        "iPay Settings", "enable_redirect"
    )
    # Above the M-Pesa ceiling the STK can't process the charge, so the page hides the
    # M-Pesa option (only hosted checkout, if enabled, can take it).
    mpesa_max = _mpesa_max_amount()
    context.mpesa_ok = not mpesa_max or context.amount <= mpesa_max
    context.mpesa_max = mpesa_max

    # Operator-only toolbar: copy the link to share, and a "back to collection" that
    # discards an unpaid bundle so its invoices return to the list. A guest paying a
    # shared link never sees these.
    is_operator = frappe.session.user != "Guest" and bool(
        set(frappe.get_roles(frappe.session.user)) & ALLOWED_ROLES
    )
    context.is_operator = is_operator
    context.pay_link = frappe.utils.get_url("/pay?token=" + token)
    context.request_name = request_name if is_operator else ""
