import json
import time
import hmac
import hashlib

import requests
import frappe
from ipay.ipay.main.utils.ipay_logs import create_log_entry


def send_callback(response_data):
    """POST the payment result to the configured callback URL.

    When a Callback Signing Secret is configured, the request is signed so the
    receiver (n8n) can verify it genuinely came from us and is not a replay:
      - the body is canonical JSON sent verbatim (so the signed bytes == the
        sent bytes);
      - X-iPay-Timestamp: unix seconds;
      - X-iPay-Signature: "sha256=" + HMAC_SHA256(secret, f"{timestamp}.{body}").
    With no secret set it sends unsigned (backward compatible).

    Returns True when the notification is considered delivered (a 2xx response,
    or no callback URL configured so there is nothing to deliver), and False
    when a configured callback URL could not be reached.
    """
    settings = frappe.get_single("iPay Settings")
    callback_url = settings.callback_url
    if not callback_url:
        return True

    body = json.dumps(response_data, separators=(",", ":"), sort_keys=True)
    headers = {"Content-Type": "application/json"}

    secret = settings.get_password("callback_secret", raise_exception=False)
    if secret:
        timestamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
        ).hexdigest()
        headers["X-iPay-Timestamp"] = timestamp
        headers["X-iPay-Signature"] = f"sha256={signature}"

    try:
        resp = requests.post(callback_url, data=body, headers=headers, timeout=15)
        resp.raise_for_status()
        create_log_entry("INF", f"Callback delivered (HTTP {resp.status_code}) to {callback_url}")
        return True
    except requests.RequestException as error:
        create_log_entry("ERR", f"Callback to {callback_url} failed: {error}")
        return False


def deliver_callback(docid, response_data):
    """Notify the n8n callback URL for an iPay Request exactly once.

    Idempotent on the request's `callback_delivered` flag, so the fast paths
    (STK success, manual confirm) and the reconcile poller never double-notify.
    Returns True if the callback is (or was already) delivered.
    """
    if frappe.db.get_value("iPay Request", docid, "callback_delivered"):
        return True

    if send_callback(response_data):
        frappe.db.set_value("iPay Request", docid, "callback_delivered", 1)
        frappe.db.commit()
        return True

    return False
