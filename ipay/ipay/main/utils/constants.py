"""Shared iPay constants and small helpers used across the payment flow.

Centralised here so the order-id cleaning, the REST hash and the amount
comparison are defined once instead of being copy-pasted into every module
that talks to iPay.
"""

import re
import hmac
import hashlib

from frappe.utils import escape_html, strip_html_tags
from frappe.utils.html_utils import unescape_html

# Characters iPay rejects in an order id. Order ids (and the `inv` field) are
# derived from Frappe document names, which can contain these, so strip them
# wherever an oid/inv is built. Must stay identical everywhere or the
# /transaction/search lookup will not match what /transact was sent.
UNWANTED_OID_CHARACTERS = r"[-/;:~`!%^*<&_]"

# How long a freshly-created, unpaid bundle is treated as "actively collecting":
# its member invoices are hidden from the collection list and a member can't spin
# up a duplicate single request. After this, the bundle is treated as abandoned —
# its invoices return to the list and can be collected individually (the bundle's
# own link still works; live-amount charging keeps that safe). Shared by
# collect_payments._drop_bundled and ipay_redirect._active_bundle_for_invoice.
ACTIVE_BUNDLE_WINDOW_MIN = 30

# A collection note is an ordinary Comment on the Sales Invoice, so it reaches the desk
# timeline for free; this marker in the (otherwise unused) subject is what keeps the collect
# app's reads payment-only. Must stay identical everywhere, like the oid characters above.
COLLECTION_NOTE_SUBJECT = "iPay Collection Note"
COLLECTION_NOTE_MAX_LENGTH = 500


def note_filters(reference_name):
    """Comment filters for the collection notes on one invoice, or on a list of them."""
    return {
        "comment_type": "Comment",
        "reference_doctype": "Sales Invoice",
        "reference_name": reference_name,
        "subject": COLLECTION_NOTE_SUBJECT,
    }


def note_content(text):
    """Store a note as escaped text wrapped in a paragraph.

    Escaping alone is not enough: the desk timeline runs every comment through
    frappe.utils.markdown, which only skips the markdown pass when is_html() is true — and
    escaping makes that false, so "![x](http://evil/p.png)" would be rendered into a live
    image. The wrapper makes is_html() true, so the note is never re-parsed."""
    return f"<p>{escape_html(text)}</p>"


def note_text(content):
    """The plain text of a stored note. Stripping is safe here (unlike on raw input, where it
    would eat "balance < 5000") because what is stored is already escaped — the only real tags
    are the wrapper, or markup a desk edit introduced."""
    return unescape_html(strip_html_tags(content or ""))


def clean_oid(name):
    """Derive an iPay-safe order id (or `inv`) from a document name."""
    return re.sub(UNWANTED_OID_CHARACTERS, "", name or "")


def search_hash(oid, vid, secret_key):
    """HMAC-SHA256 over ``oid + vid`` for the REST /transact and
    /transaction/search endpoints.

    NB: this is NOT the hosted-checkout hash (that one is HMAC-SHA1 over a
    different, ordered field set — see ipay_redirect.build_checkout_form).
    """
    return hmac.new(
        (secret_key or "").encode(), f"{oid}{vid}".encode(), hashlib.sha256
    ).hexdigest()


def amounts_match(paid, expected, tolerance=1e-2):
    """True when two money amounts are equal within a cent. Non-numeric input
    (e.g. a missing amount) is treated as 'does not match'."""
    try:
        return abs(float(paid) - float(expected)) < tolerance
    except (TypeError, ValueError):
        return False
