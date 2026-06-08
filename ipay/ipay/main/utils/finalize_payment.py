"""Single finalisation path for an iPay payment.

Every way a payment can be confirmed — the in-session STK flow (main.py), the
manual desk "Verify Payment" action (confirm_payment.py), the hosted-checkout
redirect return and the scheduled reconcile poller (reconcile_payments.py) —
ends here. Keeping one implementation guarantees the Payment Entry, the request
status and the n8n callback stay consistent regardless of which path ran.
"""

import frappe

from ipay.ipay.main.utils.make_payment_entry import make_payment_entry
from ipay.ipay.main.utils.send_callback import deliver_callback
from ipay.ipay.main.utils.constants import amounts_match


def build_response_data(data):
    """Normalise iPay's transaction-search / verify ``data`` dict into the
    canonical payload used for the Payment Entry and the n8n callback."""
    return {
        "order_id": data.get("oid"),
        "transaction_amount": data.get("transaction_amount"),
        "transaction_code": data.get("transaction_code"),
        "payee": data.get("firstname"),
        "payment_mode": data.get("payment_mode"),
        "paid_at": data.get("paid_at"),
        "telephone": data.get("telephone"),
    }


def finalize_payment(
    request_name,
    data,
    expected_amount=None,
    *,
    sales_invoice=None,
    customer=None,
    customer_email=None,
):
    """Record a found payment and finalise its iPay Request.

    Creates the (idempotent) Payment Entry, sets the request status from how the
    paid amount compares to what was expected, and delivers the n8n callback
    exactly once. Any field not supplied is read from the request itself.

    Returns the ``make_payment_entry`` result augmented with ``request_status``
    (the resolved iPay Request status, or None if the payment could not be
    recorded) and ``response_data`` (the canonical payload).
    """
    # Lock the request row for the duration of this transaction so two finalisers
    # of the SAME request (e.g. the browser-return handler and the 5-min poller
    # firing at the same instant) serialise: the second blocks here until the
    # first commits, then sees the Payment Entry already exists and resolves it
    # as a duplicate instead of racing to create a second one.
    defaults = frappe.db.get_value(
        "iPay Request",
        request_name,
        ["sales_invoice", "amount", "customer", "customer_email"],
        as_dict=True,
        for_update=True,
    ) or {}
    sales_invoice = sales_invoice or defaults.get("sales_invoice")
    customer = customer or defaults.get("customer")
    customer_email = customer_email or defaults.get("customer_email")
    if expected_amount is None:
        expected_amount = defaults.get("amount")

    response_data = build_response_data(data)

    result = make_payment_entry(
        customer, customer_email, sales_invoice, response_data, ipay_request=request_name
    )
    if result.get("status") not in ("success", "duplicate"):
        # Could not record the payment — leave the request untouched so the
        # poller retries it on the next run.
        result["request_status"] = None
        result["response_data"] = response_data
        return result

    paid = response_data.get("transaction_amount")
    status = _resolve_status(result, paid, expected_amount)

    result_detail = (
        f"KES {paid} received from {response_data.get('payee')} "
        f"({response_data.get('telephone')}) — M-Pesa ref "
        f"{response_data.get('transaction_code')}, {response_data.get('paid_at')}"
    )
    frappe.db.set_value(
        "iPay Request", request_name, {"status": status, "result_detail": result_detail}
    )
    # Commit the Payment Entry + status now, releasing the row lock BEFORE the
    # (up-to-15s) callback POST, so a second finaliser isn't blocked on the lock
    # for the duration of an HTTP call. deliver_callback is idempotent.
    frappe.db.commit()
    deliver_callback(request_name, response_data)

    result["request_status"] = status
    result["response_data"] = response_data
    return result


def _resolve_status(result, paid, expected):
    """Map a recorded payment to a request status.

    Full expected amount actually allocated to an invoice → Success. Less than
    expected → Underpaid (the balance stays outstanding and can be re-requested).
    More than expected, or an exact amount that could not be allocated because
    the invoices were already settled → Overpaid (the excess is customer credit).

    Resolution is driven purely by ``allocated`` and the paid-vs-expected amounts,
    both of which make_payment_entry reports identically for a fresh entry and a
    duplicate (re-run) — so re-running finalisation is stable and never flips a
    prior status.
    """
    allocated = frappe.utils.flt(result.get("allocated"))
    if amounts_match(paid, expected) and allocated > 0:
        return "Success"
    if frappe.utils.flt(paid) < frappe.utils.flt(expected):
        return "Underpaid"
    return "Overpaid"
