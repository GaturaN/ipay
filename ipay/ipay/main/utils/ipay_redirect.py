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


def build_checkout_form(request_name):
    """Build the field set (including the SHA1 hash) for an auto-submitting
    hosted-checkout form for the given iPay Request. The request name is sent as
    p1 so iPay echoes it back to the return handler."""
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
        "tel": req.customer_phone or "",
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


@frappe.whitelist()
def start_checkout(invoice):
    """Operator action from the collection page: ensure a submitted iPay Request
    exists for the invoice, then send the browser to the hosted checkout."""
    request_name = frappe.db.get_value(
        "iPay Request", {"sales_invoice": invoice, "docstatus": 1}, "name"
    )
    if not request_name:
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
        request_name = request.name

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/ipay_checkout?request={request_name}"
