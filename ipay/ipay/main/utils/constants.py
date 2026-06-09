"""Shared iPay constants and small helpers used across the payment flow.

Centralised here so the order-id cleaning, the REST hash and the amount
comparison are defined once instead of being copy-pasted into every module
that talks to iPay.
"""

import re
import hmac
import hashlib

# Characters iPay rejects in an order id. Order ids (and the `inv` field) are
# derived from Frappe document names, which can contain these, so strip them
# wherever an oid/inv is built. Must stay identical everywhere or the
# /transaction/search lookup will not match what /transact was sent.
UNWANTED_OID_CHARACTERS = r"[-/;:~`!%^*<&_]"


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
