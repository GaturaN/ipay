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

    oid = re.sub(UNWANTED_OID_CHARACTERS, "", req.sales_invoice)
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
        "inv": oid,
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


@frappe.whitelist()
def start_checkout(invoice):
    """Operator action from the collection page: ensure a submitted iPay Request
    exists for the invoice, then send the browser to the hosted checkout. The
    payer's number defaults to the customer's number on file (iPay requires a
    tel); the checkout page asks for one only if none is on file."""
    request_name = _ensure_request(invoice)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/ipay_checkout?request={request_name}"


@frappe.whitelist()
def prompt_mpesa(invoice, phone=None):
    """Operator action: send an M-Pesa STK push for the invoice (creating the
    iPay Request if needed). The STK + verify flow is enqueued on a background
    worker so the web request returns immediately (the verify loop can exceed the
    30s gunicorn timeout); the reconcile poller backstops finalisation."""
    request_name = _ensure_request(invoice)
    req = frappe.db.get_value(
        "iPay Request",
        request_name,
        ["customer", "customer_phone", "customer_email", "amount", "sales_invoice"],
        as_dict=True,
    )

    phone = normalize_phone(phone or req.customer_phone)
    if not phone:
        return {"status": "error", "message": "No phone number on file for this customer."}

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
    return {
        "status": "sent",
        "request": request_name,
        "message": "M-Pesa prompt sent to the customer. The payment will confirm automatically.",
    }


@frappe.whitelist()
def payment_state(request):
    """Lightweight poll target for the collection page: report whether a request
    has been paid/failed yet and the human-readable result detail."""
    row = frappe.db.get_value(
        "iPay Request", request, ["status", "result_detail"], as_dict=True
    ) or {}
    status = row.get("status") or ""
    return {
        "status": status,
        "paid": status == "Success",
        "failed": status in ("Error", "Failed to complete request"),
        "detail": row.get("result_detail") or "",
    }
