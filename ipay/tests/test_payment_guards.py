"""The "paid but unrecorded" gap (#111): naming the state, and guarding it.

A payment can arrive at iPay and still fail to reach the ledger. These tests cover the two
halves of that: finalize_payment recording the state instead of leaving the request looking
unpaid, and every charge/mutation guard refusing a request once its money has arrived.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main import main
from ipay.ipay.main.utils import finalize_payment as fp
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


# What iPay's verify/search returns for a real payment — the shape build_response_data maps.
IPAY_DATA = {
    "oid": "REQ-1",
    "transaction_amount": "100.00",
    "transaction_code": "UHS9E43HUG",
    "firstname": "FRANCIS",
    "payment_mode": "MPESA",
    "paid_at": "2026-08-28 04:18:41",
    "telephone": "254707060397",
}


class TestUnrecordedPayment(FrappeTestCase):
    """The money arrived; the Payment Entry did not. The request must say so.

    Before this, finalize_payment returned early and left the row untouched at 'Pending' —
    which every reader takes to mean "the customer has not paid"."""

    def _finalize(self, pe_result):
        defaults = frappe._dict(
            sales_invoice="INV-1", amount=100, customer="CUST-1",
            customer_email="c@x.com", docstatus=1,
        )
        with patch.object(fp, "make_payment_entry", return_value=pe_result), \
             patch.object(frappe.db, "get_value", return_value=defaults), \
             patch.object(frappe.db, "set_value") as set_value, \
             patch.object(frappe.db, "commit"), \
             patch.object(fp, "deliver_callback") as callback, \
             patch.object(fp, "notify_collection_error") as notify_error, \
             patch.object(fp, "notify_collection_success") as notify_success:
            result = fp.finalize_payment("REQ-1", IPAY_DATA, expected_amount=100)
        written = set_value.call_args[0][2] if set_value.call_args else {}
        return result, written, callback, notify_error, notify_success

    FAILED_ENTRY = {"status": "error", "payment_entry": None, "message": "boom"}
    RECORDED_ENTRY = {"status": "success", "payment_entry": "PE-1", "allocated": 100.0}

    def test_a_failed_entry_marks_the_request_received(self):
        result, written, _, _, _ = self._finalize(self.FAILED_ENTRY)
        self.assertEqual(written.get("status"), "Received")
        self.assertEqual(result["request_status"], "Received")

    def test_the_detail_says_what_arrived_and_what_to_do(self):
        # An operator reading only this field must be able to act on it.
        _, written, _, _, _ = self._finalize(self.FAILED_ENTRY)
        detail = written.get("result_detail", "")
        self.assertIn("UHS9E43HUG", detail)
        self.assertIn("NOT YET RECORDED", detail)
        self.assertIn("boom", detail)
        self.assertIn("Verify Payment", detail)

    def test_no_callback_is_delivered_for_a_payment_that_reached_no_ledger(self):
        # Downstream must never hear "paid" for money with no Payment Entry behind it.
        _, written, callback, _, _ = self._finalize(self.FAILED_ENTRY)
        callback.assert_not_called()
        self.assertNotIn("callback_payload", written)

    def test_the_collector_is_told_it_failed_not_that_it_succeeded(self):
        _, _, _, notify_error, notify_success = self._finalize(self.FAILED_ENTRY)
        notify_success.assert_not_called()
        notify_error.assert_called_once()
        self.assertIn("do not charge again", notify_error.call_args[0][1].lower())

    def test_a_recorded_payment_is_unaffected(self):
        # The happy path must be byte-for-byte what it was: status resolved, callback
        # delivered, success notified, and no error notification.
        result, written, callback, notify_error, notify_success = self._finalize(self.RECORDED_ENTRY)
        self.assertEqual(written.get("status"), "Success")
        self.assertEqual(result["request_status"], "Success")
        self.assertIn("callback_payload", written)
        callback.assert_called_once()
        notify_success.assert_called_once()
        notify_error.assert_not_called()

    def test_the_poll_can_express_the_new_state(self):
        # The collector's dialog reads these booleans; without one for Received it falls
        # through every branch and shows "still waiting".
        with patch.object(frappe.db, "get_value", return_value=frappe._dict(status="Received", result_detail="d")):
            state = rd._payment_state("REQ-1", include_detail=True)
        self.assertTrue(state["received"])
        self.assertFalse(state["paid"])
        self.assertFalse(state["partial"])
        self.assertFalse(state["failed"])

    def test_a_settled_request_is_not_reported_as_received(self):
        for status, key in (("Success", "paid"), ("Underpaid", "partial"), ("Failed", "failed")):
            with self.subTest(status=status):
                with patch.object(frappe.db, "get_value", return_value=frappe._dict(status=status)):
                    state = rd._payment_state("REQ-1")
                self.assertFalse(state["received"])
                self.assertTrue(state[key])
