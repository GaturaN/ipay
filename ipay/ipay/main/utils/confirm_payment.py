import logging

import requests
import frappe

from ipay.ipay.main.utils.ipay_logs import create_log_entry
from ipay.ipay.main.utils.constants import clean_oid, search_hash
from ipay.ipay.main.utils.finalize_payment import finalize_payment

logger = logging.getLogger(__name__)

SEARCH_URL = "https://apis.ipayafrica.com/payments/v2/transaction/search"


@frappe.whitelist(methods=["POST"])
def confirm_payment(docid, user_id, phone, amount, order, customer_email):
    """Manual desk action ("Verify Payment"): look the payment up on iPay and,
    if found, finalise it via the shared path — record the Payment Entry, set
    the request status and notify the callback. Returns the recorded result so
    the desk can show the Payment Entry link."""
    # Authorised operators only, acting on their own request (this creates a
    # Payment Entry, so it must not be callable by name for an arbitrary request).
    from ipay.ipay.main.utils.ipay_redirect import _require_operator, _require_request_access

    _require_operator()
    _require_request_access(docid)
    vendor = frappe.get_doc("iPay Settings")
    vid = (vendor.vendor_id or "").lower()
    secret_key = vendor.api_key

    # Order id is the iPay Request name (must match what initiation sent to iPay).
    oid = clean_oid(docid)
    logger.info(f"Confirming payment for request {docid} (oid {oid})")

    try:
        response = requests.post(
            SEARCH_URL,
            data={"vid": vid, "hash": search_hash(oid, vid, secret_key), "oid": oid},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json().get("data", {})

        if not data.get("transaction_code"):
            return {"status": "error", "message": "Payment not found"}

        # Allocation target is derived from the request itself inside
        # finalize_payment, NOT from the operator-supplied order/customer/amount —
        # so a payment can only ever be booked against its own request's invoice
        # (no confused-deputy diversion to an unrelated invoice).
        result = finalize_payment(docid, data)
        if result.get("status") not in ("success", "duplicate"):
            return {"status": "error", "message": result.get("message", "Could not record payment")}

        create_log_entry(
            "INF", f"Payment confirmed for iPay Request {docid}: {result.get('response_data')}"
        )
        return {
            "status": "success",
            "message": "Payment verified",
            "data": result.get("response_data"),
            "payment_entry": result.get("payment_entry"),
            "request_status": result.get("request_status"),
            "is_duplicate": result.get("status") == "duplicate",
        }

    except requests.RequestException as error:
        logger.error(f"Error during payment verification: {error}")
        return {"status": "error", "message": str(error)}
