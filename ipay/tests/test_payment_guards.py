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
            return main.lipana_mpesa("REQ-1", "u@x.com", "254700000000", "REQ1", "c@x.com", "")

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


class TestOperatorsCanSeeIt(FrappeTestCase):
    """A state nobody is prompted to look at is not much better than silence."""

    def test_the_attention_report_surfaces_an_unrecorded_payment(self):
        from ipay.ipay.report.ipay_payments_needing_attention import (
            ipay_payments_needing_attention as report,
        )

        self.assertIn("Received", report.ATTENTION_STATUSES)
        rows = [
            frappe._dict(
                name="REQ-1", status="Received", customer="CUST-1", sales_invoice="INV-1",
                amount=100, payment_entry=None, result_detail="unposted", modified="2026-08-28",
            )
        ]
        with patch.object(frappe, "get_all", return_value=rows) as get_all, \
             patch.object(frappe.db, "get_value", return_value=None):
            _columns, data = report.execute()
        # The report must ask for the new status, not just tolerate it.
        self.assertIn("Received", get_all.call_args[1]["filters"]["status"][1])
        self.assertEqual(len(data), 1)
        # No Payment Entry, so nothing was received into the books — the difference is the
        # whole expected amount, which is what an accountant needs to see.
        self.assertEqual(data[0]["received"], 0)
        self.assertEqual(data[0]["difference"], -100)

    def test_nothing_promises_an_automatic_retry_while_the_poller_is_paused(self):
        """A source check, deliberately: the defect was a user-facing sentence promising
        recovery that is switched off, which told operators to stand down while money sat
        unrecorded. It relaxes on its own if the poller is ever un-paused."""
        from ipay.ipay.main.utils.reconcile_payments import RECONCILE_PAUSED

        if not RECONCILE_PAUSED:
            self.skipTest("the reconcile poller is live again, so a retry can be promised")
        source = open(frappe.get_app_path("ipay", "ipay", "main", "main.py")).read()
        self.assertNotIn("retried automatically", source)


class TestReceivedSurvives(FrappeTestCase):
    """Recording the state is worthless if something else quietly erases it."""

    def test_the_reconcile_poller_never_abandons_a_received_payment(self):
        # The abandon check keys off a missing payment_entry — and Received has none by
        # definition. Without Received in this set the poller would mark it Abandoned, which
        # is not in MONEY_ARRIVED, so the request would become chargeable again and the
        # double-charge loop this change closes would reopen.
        from ipay.ipay.main.utils.reconcile_payments import PAID_STATUSES

        self.assertIn("Received", PAID_STATUSES)
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                self.assertIn(status, PAID_STATUSES)

    def test_a_fresh_payment_link_is_refused_once_the_money_is_in(self):
        # Underpaid is deliberately still allowed: that request owes a balance.
        with patch.object(rd, "_require_operator"), \
             patch.object(rd, "_require_redirect_enabled"), \
             patch.object(rd, "_require_request_access"), \
             patch.object(rd, "_request_awaits_cheque", side_effect=PASSED):
            for status in ("Success", "Overpaid", "Received"):
                with self.subTest(status=status):
                    with patch.object(frappe.db, "get_value", return_value=status):
                        with self.assertRaises(frappe.ValidationError):
                            rd.regenerate_payment_link("REQ-1")
            with self.subTest(status="Underpaid"):
                with patch.object(frappe.db, "get_value", return_value="Underpaid"):
                    with self.assertRaises(RuntimeError):
                        rd.regenerate_payment_link("REQ-1")

    def test_the_operator_page_treats_every_money_arrived_status_as_settled(self):
        # RequestDetail.vue hides the prompt button for a settled request. Its list is
        # hand-written in JS while MONEY_ARRIVED lives here, so nothing but this test keeps
        # the two in step — and a status missing there means the UI invites the exact action
        # the server then refuses.
        path = frappe.get_app_path("ipay", "..", "frontend", "src", "pages", "RequestDetail.vue")
        settled = open(path).read().split("const SETTLED = ")[1].split("\n")[0]
        for status in MONEY_ARRIVED:
            with self.subTest(status=status):
                self.assertIn(status, settled)


class TestThePayerIsTold(FrappeTestCase):
    """The customer's own surfaces. Money left their phone; they must not be shown a form
    inviting them to send it again, nor told we are still waiting for it."""

    def test_the_checkout_return_page_says_received_not_confirming(self):
        from ipay.www import payment_status

        for status, expected in (
            ("Received", "received"),
            ("Success", "confirmed"),
            ("Underpaid", "mismatch"),
        ):
            with self.subTest(status=status):
                ctx = frappe._dict()
                with patch.dict(frappe.form_dict, {"request": "REQ-1"}), \
                     patch.object(frappe.db, "exists", return_value=True), \
                     patch.object(frappe.db, "get_value", return_value=status):
                    payment_status.get_context(ctx)
                self.assertTrue(ctx[expected], f"{status} should set context.{expected}")
                # Received must not masquerade as a fully confirmed payment.
                if status == "Received":
                    self.assertFalse(ctx.confirmed)
                    self.assertFalse(ctx.mismatch)

    def test_the_payment_link_page_stops_asking_for_money_already_sent(self):
        from ipay.www import pay

        def context_for(status):
            ctx = frappe._dict()
            req = frappe._dict(sales_invoice="INV-1", amount=100, status=status)
            with patch.object(pay, "resolve_pay_token", return_value=("REQ-1", status)), \
                 patch.object(pay, "_mpesa_max_amount", return_value=0), \
                 patch.object(frappe.db, "get_value", return_value=req), \
                 patch.object(frappe.db, "get_single_value", return_value=0), \
                 patch.object(frappe, "get_all", return_value=["INV-1"]), \
                 patch.object(frappe, "get_roles", return_value=[]), \
                 patch.object(frappe.utils, "get_url", return_value="http://x/pay"), \
                 patch.dict(frappe.form_dict, {"token": "tok"}):
                pay.get_context(ctx)
            return ctx

        received = context_for("Received")
        self.assertTrue(received.received)
        # Not "paid": nothing is posted. The template branches on them separately.
        self.assertFalse(received.paid)

        pending = context_for("Pending")
        self.assertFalse(pending.received)

    def test_the_payment_form_is_gated_on_the_new_state(self):
        # The context flag only helps if the template actually withholds the form. The
        # defect was a customer being shown "pay now" for money they had already sent.
        path = frappe.get_app_path("ipay", "www", "pay.html")
        html = open(path).read()
        gate = [ln for ln in html.splitlines() if "not invalid" in ln and "not paid" in ln]
        self.assertTrue(gate, "could not find the payment-form gate in pay.html")
        self.assertIn("not received", gate[0])
