"""Public iPay API for other applications.

A thin, authenticated surface over the iPay transaction lookup so any external
app can confirm a payment and read its details with a single call.
"""

import requests
import frappe
from frappe import _

from ipay.ipay.main.utils.reconcile_payments import _search_transaction


@frappe.whitelist()
def get_transaction(oid):
    """Return iPay payment details for an order id (``oid``).

    Looks the payment up on iPay (scoped to this site's vendor account) and
    returns a small, easy-to-consume envelope::

        {
          "oid":  "<the oid queried>",
          "paid": true | false,
          "data": { ...full iPay record... } | null
        }

    ``paid`` is True only when iPay has a completed transaction for the oid.
    ``data`` carries the full iPay record (transaction_amount, transaction_code,
    firstname/lastname, telephone, payment_mode, paid_at, ...), or is null when
    no payment has been recorded for the oid yet.

    Authenticated endpoint (not public): the calling application authenticates
    with a Frappe API key/secret, e.g.
        Authorization: token <api_key>:<api_secret>
    """
    if not oid:
        frappe.throw(_("An oid is required."))

    settings = frappe.get_single("iPay Settings")
    vid = (settings.vendor_id or "").lower()
    secret_key = settings.api_key
    if not vid or not secret_key:
        frappe.throw(_("iPay vendor id or API key is not configured."))

    try:
        data = _search_transaction(oid, vid, secret_key)
    except requests.RequestException as error:
        frappe.throw(_("Could not reach iPay: {0}").format(error))

    return {"oid": oid, "paid": bool(data), "data": data}
