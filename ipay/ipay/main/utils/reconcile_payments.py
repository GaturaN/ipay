import requests
import frappe

from ipay.ipay.main.utils.finalize_payment import finalize_payment
from ipay.ipay.main.utils.send_callback import deliver_callback
from ipay.ipay.main.utils.ipay_logs import create_log_entry
from ipay.ipay.main.utils.constants import clean_oid, search_hash

# Kill switch for the scheduled backstop, kept so a paid external dependency can be turned
# off without a deploy. Off (False) since it polls selectively and backs off per request.
RECONCILE_PAUSED = False

# Only reconcile requests created within this window; older unconfirmed requests
# are assumed abandoned (marked terminal below) so we don't poll them forever.
RECONCILE_WINDOW_HOURS = 24

# The backstop runs every 5 minutes; a heartbeat older than this means it has
# stopped (dead scheduler / erroring job) and payments may be piling up unrecovered.
HEARTBEAT_STALE_SECONDS = 900

SEARCH_URL = "https://apis.ipayafrica.com/payments/v2/transaction/search"

# Minutes to wait before looking a request up at iPay again, indexed by how many lookups
# have already been made; the last value repeats until the reconcile window closes. The
# first rung catches the common case — a customer who took longer than the in-session
# verify window to enter their PIN — while the later rungs keep a request that is never
# going to be paid from costing a lookup every 5 minutes for a day.
POLL_BACKOFF_MINUTES = (1, 2, 5, 10, 30, 60)

# Most requests one run will touch, shared across both sweeps below. Sized against the 15s
# timeout on the calls a request can cost — _search_transaction, plus deliver_callback for
# one that turns out to be paid — so 16 still-unpaid requests take about 4 minutes, inside
# the 5-minute interval this is scheduled on. A batch that is mostly paid can exceed that,
# but those requests leave the undelivered set for good, and frappe will not start the next
# run while this one is still going. Whatever is still due waits, longest-overdue first.
RECONCILE_BATCH_SIZE = 16

# Statuses that mean a payment was recorded — these are never abandoned and stay
# eligible for callback retry. Everything else (Pending, blank legacy rows,
# Failed) with no Payment Entry is fair game for the Abandoned sweep.
# Never abandon a request in one of these: the money arrived. Success/Underpaid/Overpaid
# reached a Payment Entry; Received did not, which is precisely why it must not be abandoned
# — the abandon check below keys off a missing payment_entry, and Received has none.
PAID_STATUSES = ["Success", "Underpaid", "Overpaid", "Received"]

REQUEST_FIELDS = [
    "name", "sales_invoice", "amount", "customer", "customer_email",
    "payment_entry", "callback_payload", "poll_attempts",
]


def _next_poll_delay(poll_attempts):
    """Minutes until the next lookup, for a request looked up this many times already."""
    rung = min(frappe.utils.cint(poll_attempts), len(POLL_BACKOFF_MINUTES) - 1)
    return POLL_BACKOFF_MINUTES[rung]


def _due_or_filters(now):
    """Match a request the backstop may look up now.

    An unset next_poll_at means it has never been looked up, and counts as due: a request
    that somehow never got stamped must be polled, never skipped forever.
    """
    return [
        ["next_poll_at", "is", "not set"],
        ["next_poll_at", "<=", now],
    ]


def _claim_for_polling(requests, now):
    """Push every request in the batch down its backoff, and commit, BEFORE any lookup runs.

    Committing up front is what makes the backoff hold: _search_transaction raises on an
    errored lookup by design, and the callers below roll back on that, so a stamp written
    afterwards would be undone and an erroring request would be re-queried every run.
    It also keeps two concurrent sweeps from selecting the same rows.
    """
    for req in requests:
        frappe.db.set_value(
            "iPay Request",
            req.name,
            {
                "poll_attempts": frappe.utils.cint(req.get("poll_attempts")) + 1,
                "next_poll_at": frappe.utils.add_to_date(
                    now, minutes=_next_poll_delay(req.get("poll_attempts"))
                ),
            },
            update_modified=False,
        )
    frappe.db.commit()


def reconcile_pending_payments():
    """Scheduled backstop that guarantees a payment is finalised and the n8n
    callback delivered even when the in-session flow never completed (abandoned
    redirect, unattended Paybill, or a failed callback).

    Within the reconcile window, a submitted request whose callback has not been delivered
    is polled once its own backoff has elapsed (POLL_BACKOFF_MINUTES) — not on every run.
    Past the window, a final lookup is attempted and, if still unpaid, the request is
    marked Abandoned so it reaches a terminal state and is no longer polled. One run makes
    at most RECONCILE_BATCH_SIZE lookups. Idempotent and safe to re-run: the Payment Entry
    is deduped on the transaction code and the callback on the callback_delivered flag.
    """
    if RECONCILE_PAUSED:
        return

    settings = frappe.get_single("iPay Settings")
    vid = (settings.vendor_id or "").lower()
    secret_key = settings.api_key
    if not vid or not secret_key:
        create_log_entry("ERR", "Reconcile skipped: vendor id or api key not set")
        return

    now = frappe.utils.now_datetime()
    window_start = frappe.utils.add_to_date(now, hours=-RECONCILE_WINDOW_HOURS)

    # 1) Active window — poll the not-yet-delivered requests that are due. The flag covers
    #    both "awaiting payment" and "paid but n8n not yet notified", and _reconcile_one is
    #    idempotent, so this both finalises and (re)delivers. Longest-overdue first; an
    #    unset next_poll_at sorts ahead of any timestamp, so a request the backstop has
    #    never seen is looked up before one it is merely revisiting.
    active = frappe.get_all(
        "iPay Request",
        filters={
            "docstatus": 1,
            "callback_delivered": 0,
            "creation": [">", window_start],
        },
        or_filters=_due_or_filters(now),
        fields=REQUEST_FIELDS,
        order_by="next_poll_at asc",
        limit_page_length=RECONCILE_BATCH_SIZE,
    )

    # 2) Past the window and still undelivered (but not already Abandoned): one last
    #    lookup, then mark Abandoned UNLESS a payment was recorded. Due-gated like the
    #    active sweep — a Received request has neither payment_entry nor callback_payload,
    #    so it takes the iPay lookup path and, being in PAID_STATUSES, is never abandoned;
    #    without the gate it would be re-queried on every run for as long as it exists.
    #    In-window money comes first, so this sweep only gets what the budget has left.
    #    Skipped entirely at zero: frappe reads limit_page_length=0 as "no limit".
    stale_budget = RECONCILE_BATCH_SIZE - len(active)
    stale = (
        frappe.get_all(
            "iPay Request",
            filters={
                "docstatus": 1,
                "callback_delivered": 0,
                "creation": ["<=", window_start],
                "status": ["!=", "Abandoned"],
            },
            or_filters=_due_or_filters(now),
            fields=REQUEST_FIELDS,
            order_by="next_poll_at asc",
            limit_page_length=stale_budget,
        )
        if stale_budget
        else []
    )

    _claim_for_polling(active + stale, now)

    for req in active:
        try:
            _reconcile_one(req, vid, secret_key)
        except Exception as error:
            frappe.db.rollback()
            create_log_entry("ERR", f"Reconcile failed for {req.name}: {error}")

    # A paid request (Success/Underpaid/Overpaid) keeps its status and stays eligible for
    # callback retry; an unpaid one (Pending or Failed, no Payment Entry) becomes terminal.
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

    # Stamp liveness even on an empty run, so a stopped backstop is detectable
    # externally (reconcile_heartbeat) rather than failing silently.
    frappe.db.set_value(
        "iPay Settings", "iPay Settings", "last_reconcile_run", frappe.utils.now_datetime()
    )
    frappe.db.commit()


@frappe.whitelist()
def reconcile_heartbeat():
    """Liveness of the reconcile backstop, for an external monitor: when it last ran
    and whether that is stale. A stale heartbeat means payments may be piling up
    unrecovered, so an operator should check the scheduler."""
    last = frappe.db.get_single_value("iPay Settings", "last_reconcile_run")
    seconds_since = (
        frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(), last) if last else None
    )
    return {
        "last_run": last,
        "seconds_since": seconds_since,
        "stale": seconds_since is None or seconds_since > HEARTBEAT_STALE_SECONDS,
    }


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
        # Payment confirmed at iPay but the Payment Entry would not save — money is
        # collected yet unrecorded. finalize_payment has already alerted accounts; this is
        # the iPay Log trail for the sweep. Left undelivered so the next run retries.
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
    """Single-shot lookup of a payment by order id. Returns the data dict if a paid
    transaction is found, or None ONLY for an authoritative "no record" (a payment
    that genuinely isn't there). Any errored lookup RAISES so the caller retries and
    never treats a transient iPay failure as "not paid" (which would abandon and
    silently lose a genuinely-paid request).

    iPay uses HTTP 404 for "no record found" (still pending / never paid) — the only
    clean not-paid signal. A 5xx/HTML/unparseable response is an errored lookup, not a
    verdict, so it must raise rather than return None.
    """
    resp = requests.post(
        SEARCH_URL,
        data={"vid": vid, "hash": search_hash(oid, vid, secret_key), "oid": oid},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()  # any other non-2xx is an errored lookup — raise, don't abandon
    try:
        data = resp.json().get("data") or {}
    except ValueError:
        # 2xx but not JSON (e.g. an HTML error/maintenance page) — an errored lookup,
        # never a "not paid" verdict.
        raise requests.RequestException(f"iPay search returned a non-JSON body for {oid}")
    return data if data.get("transaction_code") else None
