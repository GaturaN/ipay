import requests
import frappe
from ipay.ipay.main.utils.ipay_logs import create_log_entry


def send_callback(response_data):
    """POST the payment result to the configured callback URL.

    Returns True when the notification is considered delivered (a 2xx response,
    or no callback URL configured so there is nothing to deliver), and False
    when a configured callback URL could not be reached.
    """
    callback_url = frappe.db.get_single_value("iPay Settings", "callback_url")
    if not callback_url:
        return True

    try:
        resp = requests.post(callback_url, json=response_data, timeout=15)
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
