import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main import main
from ipay.ipay.main.utils import ipay_redirect as rd
from ipay.ipay.main.utils.constants import MONEY_ARRIVED

# Statuses that leave a request chargeable. Every guard below must let these through, or a
# collection that legitimately needs retrying becomes impossible.
STILL_CHARGEABLE = ("Pending", "Failed", "Abandoned")

# Raised in place of the work each guard protects: if it escapes, the guard let the caller
# through. Asserting on it is what stops these tests passing for the wrong reason — a guard
# that refused everything would satisfy the refusal cases alone.
PASSED = RuntimeError("passed the guard")


class TestMoneyArrivedGuards(FrappeTestCase):
    """A request whose money has arrived must never be charged again, split, or cancelled.

    This is the regression test for a real incident (iPay Log ksloilfv8b): a payment arrived,
    the Payment Entry failed, the request stayed 'Pending', and the collector — told the
    customer had not paid — prompted the same request twice more. Two live STK pushes went out
    for money already received. 'Received' exists so those guards can see it."""

    def test_money_arrived_is_the_expected_set(self):
        # Pinned literally, NOT derived from the constant. Every other test here iterates
        # MONEY_ARRIVED, so a status quietly dropped from it would simply stop being tested
        # and the whole suite would still pass — which is exactly the regression that matters.
        self.assertEqual(
            set(MONEY_ARRIVED), {"Success", "Underpaid", "Overpaid", "Received"}
        )

    def test_the_constant_matches_the_doctype(self):
        # A status in one but not the other is how a guard silently stops guarding.
        path = frappe.get_app_path("ipay", "ipay", "doctype", "ipay_request", "ipay_request.json")
        options = next(
            f["options"] for f in json.load(open(path))["fields"] if f["fieldname"] == "status"
        ).split("\n")
        self.assertIn("Received", options)
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                self.assertIn(status, options)
        for status in STILL_CHARGEABLE:
            with self.subTest(status=status):
                self.assertIn(status, options)
                self.assertNotIn(status, MONEY_ARRIVED)

    # --- the STK rail: main.lipana_mpesa (the one the incident walked twice) -------------

    def _lipana(self, status):
        row = frappe._dict(docstatus=1, status=status)
        with patch.object(frappe.local, "request", None, create=True), \
             patch.object(frappe.db, "get_value", return_value=row), \
             patch.object(rd, "_request_awaits_cheque", side_effect=PASSED), \
             patch.object(main, "create_log_entry"):
            return main.lipana_mpesa("REQ-1", "u@x.com", "254700000000", 1, "REQ1", "c@x.com", "")

    def test_stk_is_refused_once_money_has_arrived(self):
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                self.assertEqual(self._lipana(status)["status"], "skipped")

    def test_stk_still_goes_out_for_a_chargeable_request(self):
        for status in STILL_CHARGEABLE:
            with self.subTest(status=status):
                with self.assertRaises(RuntimeError):
                    self._lipana(status)

    # --- the operator/collect rail: _enqueue_stk ----------------------------------------

    def _enqueue(self, status):
        row = frappe._dict(docstatus=1, status=status, customer_phone="254700000000")
        with patch.object(frappe.db, "get_value", return_value=row), \
             patch.object(rd, "_request_awaits_cheque", side_effect=PASSED):
            return rd._enqueue_stk("REQ-1", "254700000000")

    def test_enqueue_is_refused_once_money_has_arrived(self):
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                result = self._enqueue(status)
                self.assertEqual(result["status"], "error")
                self.assertIn("already been paid", result["message"])

    def test_enqueue_proceeds_for_a_chargeable_request(self):
        for status in STILL_CHARGEABLE:
            with self.subTest(status=status):
                with self.assertRaises(RuntimeError):
                    self._enqueue(status)

    # --- a paid bundle must not be split or cancelled out from under its payment ---------

    def _split(self, status):
        row = frappe._dict(status=status, payment_entry=None)
        with patch.object(rd, "_require_full_operator"), \
             patch.object(frappe.db, "get_value", return_value=row), \
             patch.object(frappe, "get_doc", side_effect=PASSED):
            return rd.split_bundle("REQ-1")

    def test_a_paid_bundle_cannot_be_split(self):
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                with self.assertRaises(frappe.ValidationError):
                    self._split(status)

    def test_an_unpaid_bundle_can_still_be_split(self):
        for status in STILL_CHARGEABLE:
            with self.subTest(status=status):
                with self.assertRaises(RuntimeError):
                    self._split(status)

    def _discard(self, status):
        row = frappe._dict(status=status, payment_entry=None, docstatus=1)
        with patch.object(rd, "_require_bundler"), \
             patch.object(rd, "_require_request_access"), \
             patch.object(frappe.db, "get_value", return_value=row), \
             patch.object(frappe, "get_doc", side_effect=PASSED):
            return rd.discard_bundle("REQ-1")

    def test_a_paid_bundle_cannot_be_discarded(self):
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                self.assertEqual(self._discard(status), {"cancelled": False})

    def test_an_unpaid_bundle_can_still_be_discarded(self):
        for status in STILL_CHARGEABLE:
            with self.subTest(status=status):
                with self.assertRaises(RuntimeError):
                    self._discard(status)
