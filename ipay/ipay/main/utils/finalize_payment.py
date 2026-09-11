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
from ipay.ipay.main.utils.notifications import notify_collection_error, notify_collection_success
from ipay.ipay.main.utils.alerts import notify_money_at_risk


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
    (the resolved iPay Request status, or "Received" when the money arrived but
    could not be posted) and ``response_data`` (the canonical payload).
    """
    # Lock the request row for the duration of this transaction so two finalisers
    # of the SAME request (e.g. the browser-return handler and the 5-min poller
    # firing at the same instant) serialise: the second blocks here until the
    # first commits, then sees the Payment Entry already exists and resolves it
    # as a duplicate instead of racing to create a second one.
    defaults = frappe.db.get_value(
        "iPay Request",
        request_name,
        ["sales_invoice", "amount", "customer", "customer_email", "docstatus"],
        as_dict=True,
        for_update=True,
    ) or {}
    # A payment can land on a cancelled (split/discarded) request if it was already
    # in flight when the bundle was cancelled. The money must still be recorded, so
    # we proceed — make_payment_entry allocates against LIVE outstanding, so an
    # invoice already collected elsewhere takes nothing here (the excess becomes
    # customer credit) and can't be double-charged. Flag it for an operator to eye.
    if defaults.get("docstatus") == 2:
        frappe.log_error(
            f"Payment finalised on cancelled iPay Request {request_name} — likely a "
            f"post-discard race. Recorded against live outstanding (excess = credit).",
            "iPay: payment on cancelled request",
        )
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
        # The money is real; only the ledger write failed. Say so on the request, because
        # leaving it 'Pending' reads as "the customer has not paid" — that is what let a
        # collector re-prompt a paid request twice in #111. Received also makes the charge
        # guards refuse it (constants.MONEY_ARRIVED).
        #
        # Deliberately NO callback and no callback_payload: downstream must not be told a
        # payment succeeded when nothing reached the ledger. The row lock taken above is
        # already gone — make_payment_entry rolls back on a failed insert — so this is a
        # fresh write, and it is idempotent if two finalisers land here at once.
        frappe.db.set_value(
            "iPay Request",
            request_name,
            {
                "status": "Received",
                "result_detail": (
                    f"{_received_detail(response_data)}. NOT YET RECORDED: "
                    f"{result.get('message')}. Use Verify Payment to retry."
                ),
            },
        )
        frappe.db.commit()
        notify_collection_error(
            request_name, "Payment received but not yet recorded — do not charge again."
        )
        # The collector notice above reaches whoever started the collection; this reaches
        # accounts (Error Log + the configured alert address), who would otherwise never
        # learn that money arrived and never made it into the books. Raised here rather
        # than per caller because this is the single finalisation path.
        notify_money_at_risk(
            f"Payment not recorded for {request_name}",
            f"{_received_detail(response_data)} — but the Payment Entry could not be "
            f"created: {result.get('message')}",
        )
        result["request_status"] = "Received"
        result["response_data"] = response_data
        return result

    paid = response_data.get("transaction_amount")
    status = _resolve_status(result, paid, expected_amount)

    frappe.db.set_value(
        "iPay Request",
        request_name,
        {
            "status": status,
            "result_detail": _received_detail(response_data),
            # Store the payload so the poller can retry a failed callback without
            # re-querying iPay.
            "callback_payload": frappe.as_json(response_data),
        },
    )
    # Deliver the callback while STILL holding the request row lock, then commit.
    # This keeps delivery exactly-once: a concurrent finaliser of the same request
    # blocks on the lock until we commit callback_delivered=1, then sees it and
    # skips — at the cost of blocking that (rare) concurrent finaliser for the
    # duration of the callback POST.
    deliver_callback(request_name, response_data)
    frappe.db.commit()

    if status in ("Success", "Underpaid", "Overpaid"):
        notify_collection_success(request_name, paid, response_data.get("payee"))

    result["request_status"] = status
    result["response_data"] = response_data
    return result


def _received_detail(response_data):
    """How a received payment reads on the request — the same sentence whether or not it
    reached the ledger, so an operator sees one format either way."""
    return (
        f"KES {response_data.get('transaction_amount')} received from "
        f"{response_data.get('payee')} ({response_data.get('telephone')}) — M-Pesa ref "
        f"{response_data.get('transaction_code')}, {response_data.get('paid_at')}"
    )


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
