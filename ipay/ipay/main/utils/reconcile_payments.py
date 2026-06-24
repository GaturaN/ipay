import requests
import frappe

from ipay.ipay.main.utils.finalize_payment import finalize_payment
from ipay.ipay.main.utils.send_callback import deliver_callback
from ipay.ipay.main.utils.ipay_logs import create_log_entry
from ipay.ipay.main.utils.constants import clean_oid, search_hash

# Only reconcile requests created within this window; older unconfirmed requests
# are assumed abandoned (marked terminal below) so we don't poll them forever.
RECONCILE_WINDOW_HOURS = 24

SEARCH_URL = "https://apis.ipayafrica.com/payments/v2/transaction/search"

# Statuses that mean a payment was recorded — these are never abandoned and stay
# eligible for callback retry. Everything else (Pending, blank legacy rows,
# Failed) with no Payment Entry is fair game for the Abandoned sweep.
PAID_STATUSES = ["Success", "Underpaid", "Overpaid"]

REQUEST_FIELDS = [
    "name", "sales_invoice", "amount", "customer", "customer_email",
    "payment_entry", "callback_payload",
]


def reconcile_pending_payments():
    """Scheduled backstop that guarantees a payment is finalised and the n8n
    callback delivered even when the in-session flow never completed (abandoned
    redirect, unattended Paybill, or a failed callback).

    Within the reconcile window, every submitted request whose callback has not
    been delivered is polled. Past the window, a final lookup is attempted and,
    if still unpaid, the request is marked Abandoned so it reaches a terminal
    state and is no longer polled. Idempotent and safe to re-run: the Payment
    Entry is deduped on the transaction code and the callback on the
    callback_delivered flag.
    """
    settings = frappe.get_single("iPay Settings")
    vid = (settings.vendor_id or "").lower()
    secret_key = settings.api_key
    if not vid or not secret_key:
        create_log_entry("ERR", "Reconcile skipped: vendor id or api key not set")
        return

    window_start = frappe.utils.add_to_date(
        frappe.utils.now_datetime(), hours=-RECONCILE_WINDOW_HOURS
    )

    # 1) Active window — poll every not-yet-delivered request. The flag covers
    #    both "awaiting payment" and "paid but n8n not yet notified", and
    #    _reconcile_one is idempotent, so this both finalises and (re)delivers.
    active = frappe.get_all(
        "iPay Request",
        filters={
            "docstatus": 1,
            "callback_delivered": 0,
            "creation": [">", window_start],
        },
        fields=REQUEST_FIELDS,
    )
    for req in active:
        try:
            _reconcile_one(req, vid, secret_key)
        except Exception as error:
            frappe.db.rollback()
            create_log_entry("ERR", f"Reconcile failed for {req.name}: {error}")

    # 2) Past the window and still undelivered (but not already Abandoned): one
    #    last lookup, then mark Abandoned UNLESS a payment was recorded. A paid
    #    request (Success/Underpaid/Overpaid) keeps its status and stays eligible
    #    for callback retry; an unpaid one (Pending or Failed, no Payment Entry)
    #    becomes terminal so it is no longer polled.
    stale = frappe.get_all(
        "iPay Request",
        filters={
            "docstatus": 1,
            "callback_delivered": 0,
            "creation": ["<=", window_start],
            "status": ["!=", "Abandoned"],
        },
        fields=REQUEST_FIELDS,
    )
    for req in stale:
        try:
            _reconcile_one(req, vid, secret_key)
            # Re-read the live state set by _reconcile_one. Abandon only when no
            # payment was recorded — so a payment whose callback merely failed
            # (status paid, Payment Entry present) is never mislabelled Abandoned
            # and keeps being retried for delivery.
            # Re-read under a row lock so the abandon decision is mutually
            # exclusive with finalize_payment's lock: a payment recorded for this
            # request concurrently is always observed here and never clobbered to
            # 'Abandoned'.
            current = frappe.db.get_value(
                "iPay Request", req.name, ["status", "payment_entry"],
                as_dict=True, for_update=True,
            )
            if current and not current.payment_entry and current.status not in PAID_STATUSES:
                frappe.db.set_value("iPay Request", req.name, "status", "Abandoned")
            frappe.db.commit()
        except Exception as error:
            frappe.db.rollback()
            create_log_entry("ERR", f"Reconcile (stale) failed for {req.name}: {error}")


def reconcile_request(request_name):
    """Finalise a single iPay Request on demand (used by the redirect return
    handler). Reuses the same idempotent path as the scheduled poller."""
    req = frappe.db.get_value("iPay Request", request_name, REQUEST_FIELDS, as_dict=True)
    if not req:
        return

    settings = frappe.get_single("iPay Settings")
    vid = (settings.vendor_id or "").lower()
    secret_key = settings.api_key
    if not vid or not secret_key:
        return

    _reconcile_one(req, vid, secret_key)


def _reconcile_one(req, vid, secret_key):
    # Already recorded AND we have the stored payload: retry the callback cheaply
    # instead of re-querying iPay (a 15s call) — this keeps an n8n outage from
    # re-hitting iPay for the whole paid backlog every 5 minutes. If the payload
    # is missing (a request finalised before callback_payload existed), fall
    # through to re-query iPay once, which rebuilds + stores the payload.
    # deliver_callback is idempotent on callback_delivered.
    if req.get("payment_entry") and req.get("callback_payload"):
        deliver_callback(req.name, frappe.parse_json(req.callback_payload))
        return

    if not req.sales_invoice:
        return

    # Order id is the iPay Request name (matches what initiation sent to iPay).
    oid = clean_oid(req.name)
    data = _search_transaction(oid, vid, secret_key)
    if not data:
        # Not paid yet (or not found) — leave it to retry on the next run.
        return

    # finalize_payment records the payment (allocating oldest-first against live
    # outstanding so partials clear the oldest invoices and overpayments become
    # credit), resolves the status, and delivers the callback exactly once.
    result = finalize_payment(
        req.name, data, req.amount,
        sales_invoice=req.sales_invoice, customer=req.customer,
        customer_email=req.customer_email,
    )
    if result.get("status") not in ("success", "duplicate"):
        # Payment Entry creation failed; leave undelivered to retry next run.
        create_log_entry(
            "ERR",
            f"Reconcile could not create Payment Entry for {req.name}: {result.get('message')}",
        )
        return

    request_status = result.get("request_status")
    response_data = result.get("response_data", {})
    create_log_entry(
        "INF" if request_status == "Success" else "ERR",
        f"Reconciled {req.name} ({response_data.get('transaction_code')}): "
        f"status {request_status}, paid {response_data.get('transaction_amount')} "
        f"vs expected {req.amount}",
    )


def _search_transaction(oid, vid, secret_key):
    """Single-shot lookup of a payment by order id. Returns the data dict if a
    paid transaction is found, else None.

    iPay returns HTTP 404 ("no record found") while a payment is still pending,
    so a missing transaction is treated as a quiet None rather than an error;
    only genuine transport failures raise (caught and retried by the caller).
    """
    resp = requests.post(
        SEARCH_URL,
        data={"vid": vid, "hash": search_hash(oid, vid, secret_key), "oid": oid},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    try:
        data = resp.json().get("data") or {}
    except ValueError:
        return None
    return data if data.get("transaction_code") else None
