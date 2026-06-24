import re
import hmac
import hashlib

import frappe

from ipay.ipay.main.utils.reconcile_payments import reconcile_request
from ipay.ipay.main.utils.ipay_logs import create_log_entry
from ipay.ipay.main.utils.constants import clean_oid
from ipay.ipay.main.utils.prepaid import is_sales_invoice_prepaid

# Hosted checkout (HTML form POST). NB: this flow uses HMAC-SHA1 over the
# documented field order — it is NOT the REST /transact SHA256 flow.
CHECKOUT_URL = "https://payments.ipayafrica.com/v3/ke"
HASH_FIELD_ORDER = [
    "live", "oid", "inv", "ttl", "tel", "eml", "vid",
    "curr", "p1", "p2", "p3", "p4", "cbk", "cst", "crl",
]

OPERATOR_ROLES = {"System Manager", "iPay Manager", "iPay User"}
# Collectors may prompt/collect, but only for their own work — guarded per
# invoice/request by the access checks below.
ALL_OPERATOR_ROLES = OPERATOR_ROLES | {"iPay Collector"}


def _require_full_operator():
    """Guard supervisor-only endpoints (bundling): full operators, not collectors."""
    if frappe.session.user == "Guest" or not (OPERATOR_ROLES & set(frappe.get_roles())):
        frappe.throw("Not permitted.", frappe.PermissionError)


def _require_operator():
    """Guard operator endpoints, allowing collectors. The page role-gate
    (collect_payments) does not protect the underlying whitelisted methods, so
    enforce it here too. Row-level ownership is enforced separately by
    _require_invoice_access / _require_request_access."""
    if frappe.session.user == "Guest" or not (ALL_OPERATOR_ROLES & set(frappe.get_roles())):
        frappe.throw("Not permitted.", frappe.PermissionError)


def _require_invoice_access(invoice):
    """A collector may only act on invoices that are their own work."""
    from ipay.ipay.main.utils.collector import can_access_invoice

    if not can_access_invoice(invoice):
        frappe.throw("You are not assigned to this invoice.", frappe.PermissionError)


def _require_request_access(request_name):
    """A collector may only act on requests that are their own work — closes the
    hole where any operator could poll/act on another's request by name."""
    from ipay.ipay.main.utils.collector import can_access_request

    if not can_access_request(request_name):
        frappe.throw("You are not assigned to this request.", frappe.PermissionError)


def normalize_phone(phone):
    """Normalise a Kenyan number to MSISDN form (2547XXXXXXXX / 2541XXXXXXXX).
    Returns "" for anything that is not a well-formed Kenyan mobile number, so
    callers treat junk as "no number" and prompt — rather than sending a
    malformed tel to iPay."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    elif digits.startswith(("7", "1")) and len(digits) == 9:
        digits = "254" + digits
    return digits if re.fullmatch(r"254(7|1)\d{8}", digits) else ""


def _checkout_email(entered, on_file):
    """Pick the email for hosted checkout: prefer a caller-supplied address, else
    the one on file. Returns "" for anything that is not a valid address, so the
    checkout page treats junk as "no email" and prompts — mirroring how
    normalize_phone treats a malformed number."""
    candidate = (entered or on_file or "").strip()
    return frappe.utils.validate_email_address(candidate) if candidate else ""


def build_checkout_form(request_name, phone=None, email=None):
    """Build the field set (including the SHA1 hash) for an auto-submitting
    hosted-checkout form for the given iPay Request. The request name is sent as
    p1 so iPay echoes it back to the return handler.

    iPay requires `tel` and an `eml`, and locks the M-Pesa phone field to `tel`,
    so the paying number and email must be decided here (before redirect): use the
    caller-supplied values if given, else the customer's number/email on file."""
    settings = frappe.get_single("iPay Settings")
    req = frappe.get_doc("iPay Request", request_name)

    # Order id is the iPay Request name (unique per request), not the invoice.
    oid = clean_oid(req.name)
    outstanding = frappe.db.get_value(
        "Sales Invoice", req.sales_invoice, "outstanding_amount"
    )
    amount = frappe.utils.flt(req.amount) or frappe.utils.flt(outstanding)

    cbk = frappe.utils.get_url(
        "/api/method/ipay.ipay.main.utils.ipay_redirect.ipay_return"
    )

    fields = {
        "live": "1" if settings.is_live else "0",
        "oid": oid,
        "inv": clean_oid(req.sales_invoice),
        "ttl": f"{amount:.2f}",
        "tel": normalize_phone(phone or req.customer_phone),
        "eml": _checkout_email(email, req.customer_email),
        "vid": (settings.vendor_id or "").lower(),
        "curr": "KES",
        "p1": req.name,
        "p2": "",
        "p3": "",
        "p4": "",
        "cbk": cbk,
        "cst": "0",
        "crl": "0",
    }

    data_string = "".join(fields[k] for k in HASH_FIELD_ORDER)
    fields["hsh"] = hmac.new(
        (settings.api_key or "").encode(), data_string.encode(), hashlib.sha1
    ).hexdigest()

    return CHECKOUT_URL, fields


@frappe.whitelist(allow_guest=True)
def ipay_return(**kwargs):
    """Browser return target (iPay cbk). iPay redirects here via GET after the
    customer pays. The GET status is NOT trusted: we re-verify server-side (via
    reconcile_request -> /transaction/search) before finalising, then send the
    customer to the result page. The poller backstops if the browser never returns."""
    request_name = frappe.form_dict.get("p1") or frappe.form_dict.get("request")

    try:
        if request_name:
            # Throttle the outbound iPay lookup per request so an unauthenticated
            # client can't amplify repeated GETs into a flood of 15s iPay calls;
            # the legitimate browser return fires once and the poller backstops.
            cache = frappe.cache()
            throttle_key = f"ipay_return_throttle:{request_name}"
            if not cache.get_value(throttle_key):
                cache.set_value(throttle_key, 1, expires_in_sec=10)
                reconcile_request(request_name)
    except Exception as error:
        create_log_entry(
            "ERR", f"iPay return handler failed for {request_name}: {error}"
        )

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/payment_status?request={request_name or ''}"


def _ensure_request(invoice):
    """Return the name of a submitted iPay Request for the invoice, creating one
    if none exists yet. Serialised per invoice so two concurrent operator actions
    (e.g. start_checkout + get_payment_link) can't both insert a duplicate."""
    # Lock the invoice row for the rest of this transaction; a concurrent
    # _ensure_request for the same invoice blocks here until we commit, then sees
    # the request we created and reuses it instead of inserting a second one.
    frappe.db.get_value("Sales Invoice", invoice, "name", for_update=True)
    request_name = frappe.db.get_value(
        "iPay Request", {"sales_invoice": invoice, "docstatus": 1}, "name"
    )
    if request_name:
        return request_name

    invoice_doc = frappe.get_doc("Sales Invoice", invoice)
    request = frappe.get_doc(
        {
            "doctype": "iPay Request",
            "customer": invoice_doc.customer,
            "sales_invoice": invoice,
            "docstatus": 1,
        }
    )
    request.insert(ignore_permissions=True)
    return request.name


def _payment_link_ttl_days():
    return frappe.utils.cint(
        frappe.db.get_single_value("iPay Settings", "payment_link_ttl_days")
    ) or 7


def _new_pay_token(request_name):
    """Issue a fresh token + expiry for a request, replacing any existing one."""
    token = frappe.generate_hash(length=24)
    expiry = frappe.utils.add_to_date(
        frappe.utils.now_datetime(), days=_payment_link_ttl_days()
    )
    frappe.db.set_value(
        "iPay Request", request_name, {"pay_token": token, "pay_token_expiry": expiry}
    )
    return token


def _ensure_pay_token(request_name):
    """Return the request's non-guessable payment-link token, (re)generating it
    when it is missing or has expired and stamping a fresh expiry."""
    row = frappe.db.get_value(
        "iPay Request", request_name, ["pay_token", "pay_token_expiry"], as_dict=True
    ) or {}
    token, expiry = row.get("pay_token"), row.get("pay_token_expiry")
    if token and (not expiry or frappe.utils.get_datetime(expiry) > frappe.utils.now_datetime()):
        return token
    return _new_pay_token(request_name)


def resolve_pay_token(token):
    """Resolve a payment-link token to (request_name, status), where status is
    'ok', 'expired', or 'invalid'. Used by the public pages for clear messaging."""
    if not token:
        return None, "invalid"
    row = frappe.db.get_value(
        "iPay Request", {"pay_token": token}, ["name", "pay_token_expiry", "docstatus"], as_dict=True
    )
    if not row:
        return None, "invalid"
    # A cancelled request (docstatus 2) must never be chargeable. This closes the
    # double-charge after split_bundle: the bundle is cancelled and its invoices
    # are re-created as new single requests, but its already-shared /pay link
    # otherwise still resolved to the cancelled bundle and could charge it again.
    if row.docstatus == 2:
        return None, "invalid"
    if row.pay_token_expiry and frappe.utils.get_datetime(row.pay_token_expiry) < frappe.utils.now_datetime():
        return None, "expired"
    return row.name, "ok"


def _request_from_token(token):
    """Resolve a (non-expired) payment-link token to its iPay Request name, or None."""
    return resolve_pay_token(token)[0]


def _payment_state(request_name, include_detail=False):
    row = frappe.db.get_value(
        "iPay Request", request_name, ["status", "result_detail"], as_dict=True
    ) or {}
    status = row.get("status") or ""
    state = {
        "status": status,
        "paid": status == "Success",
        # A payment was received but did not match the expected amount (the
        # balance stays outstanding, or the excess is credit). Terminal for
        # polling, but distinct from a clean full payment.
        "partial": status in ("Underpaid", "Overpaid"),
        "failed": status in ("Failed", "Abandoned"),
    }
    # result_detail embeds payer name/phone/txn — only expose to authorised operators.
    if include_detail:
        state["detail"] = row.get("result_detail") or ""
    return state


def _live_request_amount(request_name, sales_invoice):
    """Sum the live outstanding of a request's invoices (a bundle's child rows, or
    the single sales invoice) so an STK charges what is actually owed now — not a
    stored amount that goes stale when a member invoice is paid separately."""
    invoices = frappe.get_all(
        "iPay Request Invoice", filters={"parent": request_name}, pluck="sales_invoice"
    ) or [sales_invoice]
    total = 0.0
    for invoice in invoices:
        if invoice:
            total += frappe.utils.flt(
                frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")
            )
    return total


def _enqueue_stk(request_name, phone):
    """Enqueue an M-Pesa STK push on the long worker (the verify loop can exceed
    the 30s gunicorn timeout); the reconcile poller backstops finalisation."""
    req = frappe.db.get_value(
        "iPay Request",
        request_name,
        ["customer", "customer_phone", "customer_email", "sales_invoice", "status", "docstatus"],
        as_dict=True,
    )
    # Never charge a cancelled request (mirrors resolve_pay_token) — closes
    # re-charging a split/discarded bundle from the operator path; and never
    # re-prompt one that already settled, matching the customer (token) path.
    if not req or req.docstatus == 2:
        return {"status": "error", "message": "This request is no longer chargeable."}
    if req.status in ("Success", "Underpaid", "Overpaid"):
        return {"status": "error", "message": "This request has already been paid."}

    phone = normalize_phone(phone or req.customer_phone)
    if not phone:
        # Structured signal so the caller can prompt for a number and save it
        # back, rather than surfacing a dead-end error.
        return {
            "status": "missing_phone",
            "message": "No M-Pesa phone number on file. Enter a number to charge.",
        }

    # Charge the live outstanding (a member invoice may have settled since the
    # request/bundle was created), not a possibly-stale stored amount.
    amount = _live_request_amount(request_name, req.sales_invoice)
    if amount <= 0:
        return {"status": "error", "message": "Nothing left to collect on this request."}

    # Per-request cooldown: a double-click (or a retried call) can't enqueue a
    # second STK prompt for the same request within the window — the operator
    # prompt_mpesa path has no other guard (pay_prompt_mpesa adds a per-token one).
    cache = frappe.cache()
    cooldown_key = f"ipay_stk_req_cooldown:{request_name}"
    if cache.get_value(cooldown_key):
        return {
            "status": "error",
            "message": "An M-Pesa prompt was just sent for this request — please wait a moment before retrying.",
        }
    cache.set_value(cooldown_key, 1, expires_in_sec=15)

    frappe.enqueue(
        "ipay.ipay.main.main.lipana_mpesa",
        queue="long",
        docid=request_name,
        user_id=req.customer,
        phone=phone,
        amount=amount,
        oid=req.sales_invoice,
        customer_email=req.customer_email,
        payment_request_type="Mpesa Express",
    )
    return {"status": "sent", "message": "M-Pesa prompt sent. Awaiting payment."}


@frappe.whitelist(methods=["POST"])
def start_checkout(invoice):
    """Operator action from the collection page: ensure a submitted iPay Request
    (and its token) exist, then return the hosted-checkout URL for the client to
    navigate to. POST (not a GET redirect) so it can't be triggered cross-site —
    it creates and commits a request."""
    _require_operator()
    _require_invoice_access(invoice)
    request_name = _ensure_request(invoice)
    token = _ensure_pay_token(request_name)
    return {"url": f"/ipay_checkout?token={token}"}


@frappe.whitelist(methods=["POST"])
def get_payment_link(invoice=None, request=None):
    """Return a shareable, tokenised payment link for an invoice or request."""
    _require_operator()
    if request:
        _require_request_access(request)
    elif invoice:
        _require_invoice_access(invoice)
    request_name = request or (_ensure_request(invoice) if invoice else None)
    if not request_name:
        frappe.throw("An invoice or iPay Request is required.")
    token = _ensure_pay_token(request_name)
    return {
        "url": frappe.utils.get_url("/pay?token=" + token),
        "expiry": frappe.db.get_value("iPay Request", request_name, "pay_token_expiry"),
        "redirect_enabled": bool(
            frappe.db.get_single_value("iPay Settings", "enable_redirect")
        ),
    }


@frappe.whitelist(methods=["POST"])
def regenerate_payment_link(request):
    """Issue a brand-new payment link for a request (invalidating the old one) —
    e.g. when the previous link expired or was never used. Refused once there is
    nothing left to collect."""
    _require_operator()
    _require_request_access(request)
    status = frappe.db.get_value("iPay Request", request, "status")
    if status in ("Success", "Overpaid"):
        frappe.throw("This request is already paid; a new payment link is not needed.")
    token = _new_pay_token(request)
    frappe.db.commit()
    return {
        "url": frappe.utils.get_url("/pay?token=" + token),
        "expiry": frappe.db.get_value("iPay Request", request, "pay_token_expiry"),
    }


@frappe.whitelist(methods=["POST"])
def create_bundle(customer, invoices):
    """Create one submitted iPay Request covering several of a customer's
    invoices. amount = sum of their live outstanding; the oldest invoice is the
    primary. Payment is allocated oldest-first across them by make_payment_entry."""
    _require_full_operator()

    if isinstance(invoices, str):
        invoices = frappe.parse_json(invoices)
    invoices = [name for name in (invoices or []) if name]
    if not invoices:
        frappe.throw("Select at least one invoice.")

    rows = []
    total = 0.0
    companies = set()
    for name in invoices:
        si = frappe.db.get_value(
            "Sales Invoice", name, ["customer", "company", "outstanding_amount", "posting_date"], as_dict=True
        )
        if not si:
            continue
        if si.customer != customer:
            frappe.throw(f"Invoice {name} does not belong to {customer}.")
        if frappe.utils.flt(si.outstanding_amount) <= 0:
            continue
        # Prepaid invoices settle automatically — never bundle them for collection.
        if is_sales_invoice_prepaid(name):
            continue
        companies.add(si.company)
        rows.append((si.posting_date, name))
        total += frappe.utils.flt(si.outstanding_amount)

    if not rows:
        frappe.throw("None of the selected invoices need collection (paid, prepaid, or zero balance).")
    if len(companies) > 1:
        frappe.throw("All invoices in a bundle must belong to the same company.")

    rows.sort()
    primary = rows[0][1]

    request = frappe.get_doc(
        {
            "doctype": "iPay Request",
            "customer": customer,
            "sales_invoice": primary,
            "amount": f"{total:.2f}",
            "invoices": [{"sales_invoice": name} for _, name in rows],
            "docstatus": 1,
        }
    )
    request.insert(ignore_permissions=True)
    # `amount` has fetch_from the primary invoice's outstanding, which overrides
    # the bundle sum on insert; write the true total back directly.
    frappe.db.set_value("iPay Request", request.name, "amount", f"{total:.2f}")
    token = _ensure_pay_token(request.name)
    return {
        "request": request.name,
        "amount": f"{total:.2f}",
        "count": len(rows),
        "url": frappe.utils.get_url("/pay?token=" + token),
    }


@frappe.whitelist(methods=["POST"])
def split_bundle(request):
    """Split an unpaid bundle back into individual single-invoice requests and
    cancel the bundle. Only allowed before any payment is recorded."""
    _require_full_operator()
    # Lock the bundle row for the whole split so a payment landing mid-split
    # (finalize_payment takes the same row lock) is serialised against it: either
    # the payment commits first and we refuse to split, or we cancel first and the
    # payment then allocates against the now-cleared invoices — never an interleave
    # that both charges the bundle and re-issues chargeable singles.
    locked = frappe.db.get_value(
        "iPay Request", request, ["status", "payment_entry"], as_dict=True, for_update=True
    ) or {}
    if locked.get("status") in ("Success", "Underpaid", "Overpaid") or locked.get("payment_entry"):
        frappe.throw("This request has a recorded payment and cannot be split.")
    bundle = frappe.get_doc("iPay Request", request)
    invoice_names = [row.sales_invoice for row in (bundle.invoices or []) if row.sales_invoice]
    if len(invoice_names) < 2:
        frappe.throw("This is not a bundle (it covers fewer than two invoices).")

    created = []
    for name in invoice_names:
        # A legacy bundle may contain a since-prepaid invoice; skip it rather
        # than let the controller abort the whole split.
        if is_sales_invoice_prepaid(name):
            continue
        customer = frappe.db.get_value("Sales Invoice", name, "customer")
        single = frappe.get_doc(
            {
                "doctype": "iPay Request",
                "customer": customer,
                "sales_invoice": name,
                "docstatus": 1,
            }
        )
        single.insert(ignore_permissions=True)
        created.append(single.name)

    # Don't cancel the bundle if nothing was re-created (e.g. every remaining
    # invoice is prepaid) — that would silently drop the bundle.
    if not created:
        frappe.throw("All invoices in this bundle are prepaid; there is nothing to split.")

    bundle.flags.ignore_permissions = True
    bundle.cancel()
    return {"created": created}


@frappe.whitelist(methods=["POST"])
def discard_bundle(request):
    """Cancel an unpaid bundle so its member invoices return to the collection
    list — the operator created it but backed out without paying, so it should
    not linger. Locked and re-checked against a concurrent payment (like
    split_bundle); a bundle that has been paid is kept. Only bundles (requests
    with invoice rows) are discarded."""
    _require_full_operator()
    locked = frappe.db.get_value(
        "iPay Request", request, ["status", "payment_entry", "docstatus"], as_dict=True, for_update=True
    ) or {}
    # Idempotent: a second call (route guard + explicit back) on an
    # already-cancelled request is a no-op rather than an error.
    if locked.get("docstatus") != 1:
        return {"cancelled": False}
    if locked.get("status") in ("Success", "Underpaid", "Overpaid") or locked.get("payment_entry"):
        return {"cancelled": False}
    bundle = frappe.get_doc("iPay Request", request)
    if not (bundle.invoices or []):
        return {"cancelled": False}
    bundle.flags.ignore_permissions = True
    bundle.cancel()
    return {"cancelled": True}


@frappe.whitelist(methods=["POST"])
def prompt_mpesa(invoice, phone=None):
    """Operator action (collection page): send an M-Pesa STK push for an invoice."""
    _require_operator()
    _require_invoice_access(invoice)
    request_name = _ensure_request(invoice)
    result = _enqueue_stk(request_name, phone)
    result["request"] = request_name
    return result


@frappe.whitelist(methods=["POST"])
def prompt_request_mpesa(request, phone=None):
    """Operator action: send an M-Pesa STK push for an existing iPay Request — e.g.
    a bundle, charging its full amount; on payment make_payment_entry allocates
    across all the request's invoices. Single invoices use prompt_mpesa."""
    _require_operator()
    _require_request_access(request)
    result = _enqueue_stk(request, phone)
    result["request"] = request
    return result


@frappe.whitelist()
def payment_state(request):
    """Poll target for the collection page (operator, by request name)."""
    _require_operator()
    _require_request_access(request)
    return _payment_state(request, include_detail=True)


@frappe.whitelist()
def request_detail(request):
    """Detail for the SPA's request view (a bundle or single request): status,
    amount, the invoices it covers, and the payer result detail."""
    _require_operator()
    _require_request_access(request)
    req = frappe.db.get_value(
        "iPay Request",
        request,
        ["name", "customer", "customer_phone", "status", "amount", "sales_invoice", "result_detail", "docstatus"],
        as_dict=True,
    )
    if not req:
        frappe.throw("Unknown request.")

    invoices = [
        name
        for name in frappe.get_all(
            "iPay Request Invoice", filters={"parent": request}, pluck="sales_invoice"
        )
        if name
    ] or [req.sales_invoice]
    cancelled = req.docstatus == 2
    status = "Cancelled" if cancelled else (req.status or "Pending")
    is_bundle = len(invoices) > 1
    return {
        "name": req.name,
        "customer": req.customer,
        "customer_name": frappe.db.get_value("Customer", req.customer, "customer_name") or req.customer,
        # The number the STK would actually use: the request's own, else the master.
        "customer_phone": req.customer_phone
        or frappe.db.get_value("Customer", req.customer, "mobile_no")
        or "",
        "status": status,
        "amount": frappe.utils.flt(req.amount),
        "invoices": invoices,
        "is_bundle": is_bundle,
        # result_detail carries payer PII; don't echo it for a void request.
        "result_detail": "" if cancelled else (req.result_detail or ""),
        "paid": req.status == "Success",
    }


@frappe.whitelist(methods=["POST"])
def save_customer_contact(request, phone=None, email=None):
    """Persist an operator-entered phone/email so future requests never error for
    missing contact. Writes to the Customer master ONLY when that field is blank
    (never overwrites an ad-hoc number), and refreshes the in-flight request.

    Uses a low-level db.set_value because iPay operator/collector roles do not
    have Customer write permission; values are validated first."""
    _require_operator()
    _require_request_access(request)
    customer = frappe.db.get_value("iPay Request", request, "customer")
    if not customer:
        frappe.throw("Unknown request.")

    customer_updates, request_updates, saved = {}, {}, []
    if phone:
        norm = normalize_phone(phone)
        if not re.fullmatch(r"254(7|1)\d{8}", norm):
            frappe.throw("Enter a valid Kenyan phone number (e.g. 0712345678).")
        request_updates["customer_phone"] = norm
        if not frappe.db.get_value("Customer", customer, "mobile_no"):
            customer_updates["mobile_no"] = norm
            saved.append("phone")
    if email:
        valid_email = frappe.utils.validate_email_address(email)
        if not valid_email:
            frappe.throw("Enter a valid email address.")
        request_updates["customer_email"] = valid_email
        if not frappe.db.get_value("Customer", customer, "email_id"):
            customer_updates["email_id"] = valid_email
            saved.append("email")

    if customer_updates:
        frappe.db.set_value("Customer", customer, customer_updates)
    if request_updates:
        frappe.db.set_value("iPay Request", request, request_updates)
    return {"status": "ok", "saved_to_customer": saved}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def pay_prompt_mpesa(token, phone):
    """Customer action on the payment-link page: STK push, authorised by token.
    Guarded against already-paid requests and rate-limited per token to prevent
    using a shared link to spam STK prompts."""
    request_name = _request_from_token(token)
    if not request_name:
        return {"status": "error", "message": "Invalid or expired payment link."}
    if _payment_state(request_name)["paid"]:
        return {"status": "error", "message": "This invoice has already been paid."}

    cache = frappe.cache()
    cooldown_key = f"ipay_stk_cooldown:{token}"
    count_key = f"ipay_stk_count:{token}"
    if cache.get_value(cooldown_key):
        return {"status": "error", "message": "Please wait a moment before requesting another prompt."}
    if int(cache.get_value(count_key) or 0) >= 5:
        return {"status": "error", "message": "Too many attempts. Please try again later."}
    cache.set_value(cooldown_key, 1, expires_in_sec=30)
    cache.set_value(count_key, int(cache.get_value(count_key) or 0) + 1, expires_in_sec=3600)

    return _enqueue_stk(request_name, phone)


@frappe.whitelist(allow_guest=True)
def pay_state(token):
    """Poll target for the payment-link page (customer, by token). Returns only
    coarse status — never the PII-bearing result_detail — to unauthenticated callers."""
    request_name = _request_from_token(token)
    if not request_name:
        return {"status": "", "paid": False, "failed": False}
    return _payment_state(request_name)
