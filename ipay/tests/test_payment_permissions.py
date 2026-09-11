"""Who the app is acting as when it writes the M-Pesa Payment Entry.

A payment is finalised by whichever rail confirmed it, and two of those rails are
unauthenticated: the customer's /pay link and the hosted-checkout return both arrive as
Guest (frappe.enqueue carries the enqueuing user into the worker). The collector's STK
rail arrives as an iPay Collector. None of those identities holds Payment Entry
permission, and ERPNext's own validation checks it against the SESSION user — which
ignore_permissions cannot reach. So those rails write as Administrator and restore the
caller afterwards.

Callers who can already write the entry are deliberately NOT elevated: frappe.set_user
resets the session's data, and an authenticated operator's CSRF token lives there.

These tests pin all of it — the write happens elevated where it must, does not where it
need not, and the session always comes back. A leaked Administrator session would be far
worse than the bug being fixed.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main.utils import make_payment_entry as mpe

# What iPay's verify/search returns for a real payment.
RESPONSE = {
    "order_id": "REQ-1",
    "transaction_amount": "100.00",
    "transaction_code": "UHS9E43HUG",
    "payee": "FRANCIS",
    "payment_mode": "MPESA",
    "paid_at": "2026-09-11 04:18:41",
    "telephone": "254707060397",
}

# The identities that actually reach make_payment_entry, and whether they may write a
# Payment Entry unaided. The guest rails and the collector may not — that is the whole point.
GUEST = "Guest"
COLLECTOR = "collector@example.com"
ACCOUNTS = "accounts@example.com"
UNPRIVILEGED = (GUEST, COLLECTOR)

# Stands in for ERPNext's permission barrier: validate() -> set_missing_values() ->
# get_account_details() -> frappe.has_permission("Payment Entry", throw=True), which reads
# frappe.session.user and never sees the document's ignore_permissions flag. Raising on the
# session identity is what stops these tests passing for the wrong reason: a fix that set the
# flag but not the session would still fail here, as it does in production.
PRIVILEGED = frozenset({"Administrator", ACCOUNTS})


class _FakePaymentEntry:
    """Records the identity in force at each write, so the test can assert on it."""

    def __init__(self, session, fail_with=None):
        object.__setattr__(self, "_d", {"session": session, "fail_with": fail_with})
        self.name = None
        self.references = []
        self.inserted_as = None
        self.submitted_as = None
        self.insert_ignored_permissions = None

    def __setattr__(self, key, value):
        self._d[key] = value

    def __getattr__(self, key):
        try:
            return object.__getattribute__(self, "_d")[key]
        except KeyError:
            raise AttributeError(key)

    def append(self, table, row):
        self._d.setdefault(table, []).append(row)

    def _check(self):
        if self._d["session"].user not in PRIVILEGED:
            raise frappe.PermissionError(
                f"No permission to create Payment Entry as {self._d['session'].user}"
            )

    def insert(self, ignore_permissions=False, **kwargs):
        self._d["insert_ignored_permissions"] = ignore_permissions
        self._check()
        if self._d["fail_with"]:
            raise self._d["fail_with"]
        self._d["name"] = "PE-0001"
        self._d["inserted_as"] = self._d["session"].user
        # frappe stamps owner from the session user (document.py:594-605), so the fake must
        # too — otherwise a restamp regression shows up as a missing mock, not as wrong owner.
        self._d["owner"] = self._d["session"].user
        return self

    def db_set(self, field, value, **kwargs):
        self._d[field] = value

    def submit(self):
        self._check()
        self._d["docstatus"] = 1
        self._d["submitted_as"] = self._d["session"].user
        return self


class TestPaymentEntryIsWrittenWithPermission(FrappeTestCase):
    """The M-Pesa rails must record the payment whoever confirmed it.

    Before this, an unprivileged finaliser's insert was refused, make_payment_entry
    returned 'error', and finalize_payment marked the request 'Received — NOT YET
    RECORDED': the money had arrived and the ledger never heard about it."""

    def _finalize(self, caller, fail_with=None, won_by=None):
        """Run make_payment_entry as `caller`. Returns (result, entry, session, hops).

        `won_by` models a CONCURRENT finaliser: the idempotency check at the top of
        make_payment_entry finds nothing, and only the re-read after the failed insert
        sees the winner's entry. Seeding it on the first read instead would return a
        duplicate before reaching the write, testing nothing about elevation."""
        session = frappe._dict(user=caller)
        hops = []

        def set_user(user):
            hops.append(user)
            session.user = user

        entry = _FakePaymentEntry(session, fail_with=fail_with)
        invoice = frappe._dict(
            name="INV-1", outstanding_amount=100.0, posting_date="2026-09-01",
            customer="CUST-1", customer_name="Acme Ltd", company="Acme Co",
        )

        lookups = []

        def get_value(doctype, name, fields=None, **kwargs):
            if doctype == "Sales Invoice":
                return invoice
            if doctype == "Payment Entry":
                if not isinstance(name, dict):
                    return 0.0
                lookups.append(name)
                return won_by if len(lookups) > 1 else None
            return None

        # The same question the code asks before elevating, answered per session identity.
        def has_permission(doctype, ptype="read", **kwargs):
            return session.user in PRIVILEGED

        with patch.object(frappe, "session", session), \
             patch.object(frappe, "set_user", set_user), \
             patch.object(frappe, "has_permission", has_permission), \
             patch.object(frappe, "new_doc", return_value=entry), \
             patch.object(frappe.db, "get_value", side_effect=get_value), \
             patch.object(frappe.db, "set_value"), \
             patch.object(frappe.db, "get_single_value", return_value=None), \
             patch.object(frappe.db, "rollback"), \
             patch.object(frappe, "get_all", return_value=[]), \
             patch.object(frappe, "get_cached_value", return_value="Cash - AC"), \
             patch.object(frappe, "log_error"):
            result = mpe.make_payment_entry(
                "CUST-1", "c@x.com", "INV-1", RESPONSE, ipay_request="REQ-1"
            )
        return result, entry, session, hops

    # --- the money reaches the ledger ---------------------------------------------------

    def test_a_payment_entry_is_created_by_an_unprivileged_caller(self):
        # The collector's STK rail: an iPay Collector holds no Payment Entry permission.
        result, entry, _, _ = self._finalize(COLLECTOR)
        self.assertEqual(result["status"], "success")
        self.assertEqual(entry.inserted_as, "Administrator")

    def test_a_guest_finalisation_still_records(self):
        # The /pay link and the hosted-checkout return both arrive as Guest.
        result, entry, _, _ = self._finalize(GUEST)
        self.assertEqual(result["status"], "success")
        self.assertEqual(entry.inserted_as, "Administrator")

    def test_the_entry_is_submitted_not_left_as_a_draft(self):
        # Unlike a collected cheque, an M-Pesa payment is already in the bank: it posts.
        # Submitting is the step that settles the invoice, so it must be elevated too.
        for caller in UNPRIVILEGED:
            with self.subTest(caller=caller):
                _, entry, _, _ = self._finalize(caller)
                self.assertEqual(entry.docstatus, 1)
                self.assertEqual(entry.submitted_as, "Administrator")

    def test_a_privileged_caller_is_unaffected(self):
        # The desk "Verify Payment" rail worked before and must still work.
        result, entry, session, _ = self._finalize(ACCOUNTS)
        self.assertEqual(result["status"], "success")
        self.assertEqual(session.user, ACCOUNTS)
        self.assertEqual(entry.inserted_as, ACCOUNTS)

    def test_a_caller_who_already_has_permission_is_never_elevated(self):
        # Elevating costs the caller their session data — frappe.set_user resets it, and the
        # CSRF token lives there. An operator who can already write the entry must not pay
        # that price, so the elevation is skipped entirely rather than applied and undone.
        for caller in (ACCOUNTS, "Administrator"):
            with self.subTest(caller=caller):
                _, _, session, hops = self._finalize(caller)
                self.assertEqual(hops, [])
                self.assertEqual(session.user, caller)

    def test_the_write_does_not_rely_on_document_permissions_alone(self):
        # ignore_permissions is passed for parity with record_cheque, but it is the session
        # change that clears the barrier — this pins that the flag is actually sent.
        _, entry, _, _ = self._finalize(GUEST)
        self.assertTrue(entry.insert_ignored_permissions)

    def test_an_elevated_entry_is_owned_by_administrator(self):
        # Deliberately NOT record_cheque's behaviour, which restamps owner to the collector
        # (ipay_redirect.py:1093) so a physical cheque can be traced from field to bank. There
        # is no custody chain for M-Pesa and on the guest rails there is no person to credit —
        # "Guest" as the owner of a submitted Payment Entry would be worse than Administrator.
        # The payer is identified in remarks instead. Both branches are pinned, because the
        # unelevated rail keeping its own owner is the reason this divergence is safe.
        _, entry, _, _ = self._finalize(GUEST)
        self.assertEqual(entry.owner, "Administrator")
        _, entry, _, _ = self._finalize(ACCOUNTS)
        self.assertEqual(entry.owner, ACCOUNTS)

    # --- and the session always comes back ----------------------------------------------

    def test_the_session_is_restored_after_the_write(self):
        # A leaked Administrator session would be far worse than the bug being fixed:
        # everything the caller did next would run unchecked. Asserted as the whole round
        # trip, so code that never elevates fails here too rather than passing vacuously.
        for caller in UNPRIVILEGED:
            with self.subTest(caller=caller):
                _, _, session, hops = self._finalize(caller)
                self.assertEqual(hops, ["Administrator", caller])
                self.assertEqual(session.user, caller)

    def test_the_session_is_restored_when_the_write_fails(self):
        # The failure path must not strand an elevated session either. No existing entry,
        # so make_payment_entry re-raises internally and reports the error.
        result, _, session, hops = self._finalize(GUEST, fail_with=ValueError("insert refused"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(hops, ["Administrator", GUEST])
        self.assertEqual(session.user, GUEST)

    def test_the_session_is_restored_on_the_concurrent_duplicate_path(self):
        # A concurrent finaliser won the race: this caller returns the winner's entry and
        # must still hand the session back on the way out.
        result, _, session, hops = self._finalize(
            GUEST, fail_with=ValueError("duplicate reference_no"), won_by="PE-0002"
        )
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["payment_entry"], "PE-0002")
        self.assertEqual(hops, ["Administrator", GUEST])
        self.assertEqual(session.user, GUEST)

    # --- elevating must not open a new way in -------------------------------------------

    def test_make_payment_entry_is_not_callable_over_http(self):
        # It now writes as Administrator, so it must stay server-side only: reachable just
        # through finalize_payment, after the payment has been verified against iPay.
        self.assertNotIn(mpe.make_payment_entry, frappe.whitelisted)
