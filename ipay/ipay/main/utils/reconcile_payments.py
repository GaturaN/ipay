import re
import hmac
import hashlib
import requests
import frappe

from ipay.ipay.main.utils.make_payment_entry import make_payment_entry
from ipay.ipay.main.utils.send_callback import deliver_callback
from ipay.ipay.main.utils.ipay_logs import create_log_entry

# Order ids are derived from the Sales Invoice exactly as the original /transact
# request did (see main.py / confirm_payment.py), so the search matches.
UNWANTED_OID_CHARACTERS = r"[-/;:~`!%^*<&_]"

# Only reconcile requests created within this window; older unconfirmed requests
# are assumed abandoned and are left alone (so we don't poll forever).
RECONCILE_WINDOW_HOURS = 24

SEARCH_URL = "https://apis.ipayafrica.com/payments/v2/transaction/search"


def reconcile_pending_payments():
    """Scheduled backstop that guarantees a payment is finalised and the n8n
    callback is delivered even when the in-session flow never completed
    (abandoned redirect, unattended Paybill, or a failed callback).

    Polls iPay for every submitted iPay Request whose callback has not yet been
    delivered, within the reconcile window. Idempotent and safe to re-run: the
    Payment Entry is deduped on the transaction code and the callback on the
    callback_delivered flag.
    """
    window_start = frappe.utils.add_to_date(
        frappe.utils.now_datetime(), hours=-RECONCILE_WINDOW_HOURS
    )
    pending = frappe.get_all(
        "iPay Request",
        filters={
            "docstatus": 1,
            "callback_delivered": 0,
            "creation": [">", window_start],
        },
        fields=["name", "sales_invoice", "amount", "customer", "customer_email"],
    )
    if not pending:
        return

    settings = frappe.get_single("iPay Settings")
    vid = (settings.vendor_id or "").lower()
    secret_key = settings.api_key
    if not vid or not secret_key:
        create_log_entry("ERR", "Reconcile skipped: vendor id or api key not set")
        return

    for req in pending:
        try:
            _reconcile_one(req, vid, secret_key)
        except Exception as error:
            frappe.db.rollback()
            create_log_entry("ERR", f"Reconcile failed for {req.name}: {error}")


def reconcile_request(request_name):
    """Finalise a single iPay Request on demand (used by the redirect return
    handler). Verifies the payment, creates the Payment Entry and delivers the
    n8n callback, reusing the same idempotent path as the scheduled poller."""
    req = frappe.db.get_value(
        "iPay Request",
        request_name,
        ["name", "sales_invoice", "amount", "customer", "customer_email"],
        as_dict=True,
    )
    if not req:
        return

    settings = frappe.get_single("iPay Settings")
    vid = (settings.vendor_id or "").lower()
    secret_key = settings.api_key
    if not vid or not secret_key:
        return

    _reconcile_one(req, vid, secret_key)


def _reconcile_one(req, vid, secret_key):
    if not req.sales_invoice:
        return

    oid = re.sub(UNWANTED_OID_CHARACTERS, "", req.sales_invoice)
    data = _search_transaction(oid, vid, secret_key)
    if not data:
        # Not paid yet (or not found) — leave it to retry on the next run.
        return

    response_data = {
        "order_id": data.get("oid"),
        "transaction_amount": data.get("transaction_amount"),
        "transaction_code": data.get("transaction_code"),
        "payee": data.get("firstname"),
        "payment_mode": data.get("payment_mode"),
        "paid_at": data.get("paid_at"),
        "telephone": data.get("telephone"),
    }

    if _amount_matches(data.get("transaction_amount"), req.amount):
        result = make_payment_entry(
            req.customer, req.customer_email, req.sales_invoice, response_data, ipay_request=req.name
        )
        if result.get("status") in ("success", "duplicate"):
            frappe.db.set_value("iPay Request", req.name, "status", "Success")
            deliver_callback(req.name, response_data)
            create_log_entry(
                "INF",
                f"Reconciled payment for {req.name} ({response_data['transaction_code']})",
            )
        else:
            # Payment Entry creation failed; leave undelivered to retry next run.
            create_log_entry(
                "ERR",
                f"Reconcile could not create Payment Entry for {req.name}: {result.get('message')}",
            )
    else:
        # Paid, but the amount differs from the invoice — notify and flag for
        # manual reconciliation; do not auto-create a Payment Entry.
        frappe.db.set_value("iPay Request", req.name, "status", "Amount Mismatch")
        deliver_callback(req.name, response_data)
        create_log_entry(
            "ERR",
            f"Amount mismatch for {req.name}: paid {response_data['transaction_amount']} vs expected {req.amount}",
        )

    frappe.db.commit()


def _search_transaction(oid, vid, secret_key):
    """Single-shot lookup of a payment by order id. Returns the data dict if a
    paid transaction is found, else None.

    iPay returns HTTP 404 ("no record found") while a payment is still pending,
    so a missing transaction is treated as a quiet None rather than an error;
    only genuine transport failures raise (caught and retried by the caller).
    """
    hash_value = hmac.new(
        secret_key.encode(), f"{oid}{vid}".encode(), hashlib.sha256
    ).hexdigest()
    resp = requests.post(
        SEARCH_URL,
        data={"vid": vid, "hash": hash_value, "oid": oid},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    try:
        data = resp.json().get("data") or {}
    except ValueError:
        return None
    return data if data.get("transaction_code") else None


def _amount_matches(transaction_amount, expected_amount):
    try:
        return abs(float(transaction_amount) - float(expected_amount)) < 1e-2
    except (TypeError, ValueError):
        return False
