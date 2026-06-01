import re
import hmac
import hashlib

import frappe

from ipay.ipay.main.utils.reconcile_payments import reconcile_request
from ipay.ipay.main.utils.ipay_logs import create_log_entry

# Hosted checkout (HTML form POST). NB: this flow uses HMAC-SHA1 over the
# documented field order — it is NOT the REST /transact SHA256 flow.
CHECKOUT_URL = "https://payments.ipayafrica.com/v3/ke"
UNWANTED_OID_CHARACTERS = r"[-/;:~`!%^*<&_]"
HASH_FIELD_ORDER = [
    "live", "oid", "inv", "ttl", "tel", "eml", "vid",
    "curr", "p1", "p2", "p3", "p4", "cbk", "cst", "crl",
]

OPERATOR_ROLES = {"System Manager", "iPay Manager", "iPay User"}


def _require_operator():
    """Guard operator-only endpoints. The page role-gate (collect_payments) does
    not protect the underlying whitelisted methods, so enforce it here too."""
    if frappe.session.user == "Guest" or not (OPERATOR_ROLES & set(frappe.get_roles())):
        frappe.throw("Not permitted.", frappe.PermissionError)


def normalize_phone(phone):
    """Normalise a Kenyan number to MSISDN form (2547XXXXXXXX / 2541XXXXXXXX):
    strip non-digits and the leading +/0, so iPay charges a consistent number."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if digits.startswith("254"):
        return digits
    if digits.startswith("0"):
        return "254" + digits[1:]
    if digits.startswith(("7", "1")):
        return "254" + digits
    return digits


def build_checkout_form(request_name, phone=None):
    """Build the field set (including the SHA1 hash) for an auto-submitting
    hosted-checkout form for the given iPay Request. The request name is sent as
    p1 so iPay echoes it back to the return handler.

    iPay requires `tel` and locks the M-Pesa phone field to it, so the paying
    number must be decided here (before redirect): use the caller-supplied phone
    if given, else the customer's number on file."""
    settings = frappe.get_single("iPay Settings")
    req = frappe.get_doc("iPay Request", request_name)

    # Order id is the iPay Request name (unique per request), not the invoice.
    oid = re.sub(UNWANTED_OID_CHARACTERS, "", req.name)
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
        "inv": re.sub(UNWANTED_OID_CHARACTERS, "", req.sales_invoice),
        "ttl": f"{amount:.2f}",
        "tel": normalize_phone(phone or req.customer_phone),
        "eml": req.customer_email or "",
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
            reconcile_request(request_name)
    except Exception as error:
        create_log_entry(
            "ERR", f"iPay return handler failed for {request_name}: {error}"
        )

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/payment_status?request={request_name or ''}"


def _ensure_request(invoice):
    """Return the name of a submitted iPay Request for the invoice, creating one
    if none exists yet."""
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


def _ensure_pay_token(request_name):
    """Return the request's non-guessable payment-link token, generating it on
    first use."""
    token = frappe.db.get_value("iPay Request", request_name, "pay_token")
    if not token:
        token = frappe.generate_hash(length=24)
        frappe.db.set_value("iPay Request", request_name, "pay_token", token)
    return token


def _request_from_token(token):
    """Resolve a payment-link token to its iPay Request name, or None."""
    if not token:
        return None
    return frappe.db.get_value("iPay Request", {"pay_token": token}, "name")


def _payment_state(request_name, include_detail=False):
    row = frappe.db.get_value(
        "iPay Request", request_name, ["status", "result_detail"], as_dict=True
    ) or {}
    status = row.get("status") or ""
    state = {
        "status": status,
        "paid": status == "Success",
        "failed": status in ("Error", "Failed to complete request"),
    }
    # result_detail embeds payer name/phone/txn — only expose to authorised operators.
    if include_detail:
        state["detail"] = row.get("result_detail") or ""
    return state


def _enqueue_stk(request_name, phone):
    """Enqueue an M-Pesa STK push on the long worker (the verify loop can exceed
    the 30s gunicorn timeout); the reconcile poller backstops finalisation."""
    req = frappe.db.get_value(
        "iPay Request",
        request_name,
        ["customer", "customer_phone", "customer_email", "amount", "sales_invoice"],
        as_dict=True,
    )
    phone = normalize_phone(phone or req.customer_phone)
    if not phone:
        return {"status": "error", "message": "No phone number provided."}

    frappe.enqueue(
        "ipay.ipay.main.main.lipana_mpesa",
        queue="long",
        docid=request_name,
        user_id=req.customer,
        phone=phone,
        amount=req.amount,
        oid=req.sales_invoice,
        customer_email=req.customer_email,
        payment_request_type="Mpesa Express",
    )
    return {"status": "sent", "message": "M-Pesa prompt sent. Awaiting payment."}


@frappe.whitelist()
def start_checkout(invoice):
    """Operator action from the collection page: ensure a submitted iPay Request
    (and its token) exist, then send the browser to the hosted checkout."""
    _require_operator()
    request_name = _ensure_request(invoice)
    token = _ensure_pay_token(request_name)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/ipay_checkout?token={token}"


@frappe.whitelist()
def get_payment_link(invoice=None, request=None):
    """Return a shareable, tokenised payment link for an invoice or request."""
    _require_operator()
    request_name = request or (_ensure_request(invoice) if invoice else None)
    if not request_name:
        frappe.throw("An invoice or iPay Request is required.")
    token = _ensure_pay_token(request_name)
    return {
        "url": frappe.utils.get_url("/pay?token=" + token),
        "redirect_enabled": bool(
            frappe.db.get_single_value("iPay Settings", "enable_redirect")
        ),
    }


@frappe.whitelist()
def prompt_mpesa(invoice, phone=None):
    """Operator action (collection page): send an M-Pesa STK push for an invoice."""
    _require_operator()
    request_name = _ensure_request(invoice)
    result = _enqueue_stk(request_name, phone)
    result["request"] = request_name
    return result


@frappe.whitelist()
def payment_state(request):
    """Poll target for the collection page (operator, by request name)."""
    _require_operator()
    return _payment_state(request, include_detail=True)


@frappe.whitelist(allow_guest=True)
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
