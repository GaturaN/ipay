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
