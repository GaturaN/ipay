import requests
import frappe
from ipay.ipay.main.utils.ipay_logs import create_log_entry


def send_callback(response_data):
    """POST the payment result to the configured callback URL, if one is set."""
    callback_url = frappe.db.get_single_value("iPay Settings", "callback_url")
    if not callback_url:
        return

    try:
        resp = requests.post(callback_url, json=response_data, timeout=15)
        resp.raise_for_status()
        create_log_entry("INF", f"Callback delivered (HTTP {resp.status_code}) to {callback_url}")
    except requests.RequestException as error:
        create_log_entry("ERR", f"Callback to {callback_url} failed: {error}")
