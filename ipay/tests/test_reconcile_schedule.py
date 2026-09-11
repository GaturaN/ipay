"""The reconcile backstop's polling schedule.

d1e8472 paused the sweep because it re-queried iPay once per undelivered request on every
run with no memory between runs, and asked for selective polling with per-request backoff
before it was resumed. These tests cover what makes resuming safe: the backoff schedule,
the due gate that keeps a request from being polled early, the per-run budget that stops a
run outlasting its own interval, and the guard that a cancelled request is never polled.

Pure/mock like the rest of ipay/tests — no rows are written.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main import main
from ipay.ipay.main.utils import ipay_redirect as rd
from ipay.ipay.main.utils import reconcile_payments as rp
from ipay.ipay.main.utils import finalize_payment as fp
from ipay.ipay.main.utils.constants import MONEY_ARRIVED

# Stands in for an iPay Request row as frappe.get_all returns it.
def _row(name, poll_attempts=0):
    return frappe._dict(
        name=name, sales_invoice="SINV-1", amount=100, customer="C-1",
        customer_email="c@example.com", payment_entry=None, callback_payload=None,
        poll_attempts=poll_attempts,
    )


class TestPollBackoff(FrappeTestCase):
    """How long the backstop waits before looking a request up again. Too eager and it is
    the call-volume problem d1e8472 paused it for; too lazy and money sits unrecorded."""

    def test_each_attempt_takes_the_next_rung(self):
        # Pinned literally, NOT derived from the constant — a schedule quietly rewritten
        # would otherwise still pass, and the schedule is the whole point of this change.
        self.assertEqual(
            [rp._next_poll_delay(n) for n in range(6)], [1, 2, 5, 10, 30, 60]
        )

    def test_the_last_rung_repeats_instead_of_running_off_the_end(self):
        beyond = len(rp.POLL_BACKOFF_MINUTES) + 5
        for attempts in range(len(rp.POLL_BACKOFF_MINUTES), beyond):
            with self.subTest(attempts=attempts):
                self.assertEqual(rp._next_poll_delay(attempts), rp.POLL_BACKOFF_MINUTES[-1])

    def test_a_request_with_no_attempts_yet_gets_the_first_rung(self):
        # poll_attempts is blank on every request that predates this change.
        self.assertEqual(rp._next_poll_delay(None), rp.POLL_BACKOFF_MINUTES[0])
        self.assertEqual(rp._next_poll_delay(0), rp.POLL_BACKOFF_MINUTES[0])

    def test_the_schedule_is_terminal_inside_the_reconcile_window(self):
        """The backoff must not stretch past the 24h window, or a request would leave the
        active sweep still holding unused attempts and never get its final lookup."""
        elapsed = attempts = 0
        while elapsed < rp.RECONCILE_WINDOW_HOURS * 60:
            elapsed += rp._next_poll_delay(attempts)
            attempts += 1
        # Reaches the boundary in far fewer lookups than the 288/day that caused the pause.
        self.assertLess(attempts, 40)
        self.assertGreater(attempts, 1)


class TestDueGate(FrappeTestCase):
    """Which requests a run is allowed to look up."""

    def test_a_request_whose_wait_has_not_elapsed_is_not_polled(self):
        now = frappe.utils.now_datetime()
        conditions = rp._due_or_filters(now)
        self.assertIn(["next_poll_at", "<=", now], conditions)
        # The gate is an upper bound on next_poll_at, so a future stamp cannot match it.
        future = frappe.utils.add_to_date(now, minutes=30)
        self.assertGreater(future, now)

    def test_a_request_never_polled_is_due(self):
        # Blank next_poll_at means the backstop has never seen it. It must be polled, not
        # skipped forever — this is what keeps a missed stamp from stranding a payment.
        self.assertIn(["next_poll_at", "is", "not set"], rp._due_or_filters(frappe.utils.now_datetime()))

    def test_the_gate_is_only_about_the_poll_stamp(self):
        # Anything else in here would silently widen or narrow which payments get chased.
        for condition in rp._due_or_filters(frappe.utils.now_datetime()):
            with self.subTest(condition=condition):
                self.assertEqual(condition[0], "next_poll_at")


class TestClaimBeforePolling(FrappeTestCase):
    """The batch is stamped and committed before the first lookup. That is what makes the
    backoff survive an errored lookup, and what keeps two runs off the same rows."""

    def test_claiming_advances_the_attempt_count_and_pushes_the_next_poll_out(self):
        now = frappe.utils.now_datetime()
        rows = [_row("IPREQ-1", poll_attempts=0), _row("IPREQ-2", poll_attempts=3)]
        written = {}
        with patch.object(frappe.db, "set_value", side_effect=lambda dt, n, v, **kw: written.__setitem__(n, v)), \
             patch.object(frappe.db, "commit"):
            rp._claim_for_polling(rows, now)

        self.assertEqual(written["IPREQ-1"]["poll_attempts"], 1)
        self.assertEqual(written["IPREQ-2"]["poll_attempts"], 4)
        # The delay is chosen from the attempts made BEFORE this poll.
        self.assertEqual(
            written["IPREQ-1"]["next_poll_at"],
            frappe.utils.add_to_date(now, minutes=rp._next_poll_delay(0)),
        )
        self.assertEqual(
            written["IPREQ-2"]["next_poll_at"],
            frappe.utils.add_to_date(now, minutes=rp._next_poll_delay(3)),
        )

    def test_the_sweep_claims_the_whole_batch_before_it_polls_anything(self):
        """Without this call the backoff does not exist: every due request would be looked
        up again on the very next run, which is the state that had the sweep paused."""
        order = []
        active = [_row("IPREQ-1"), _row("IPREQ-2")]
        stale = [_row("IPREQ-OLD")]

        def fake_get_all(doctype, **kwargs):
            in_window = kwargs["filters"]["creation"][0] == ">"
            return list(active if in_window else stale)[: kwargs["limit_page_length"]]

        settings = frappe._dict(vendor_id="VID", api_key="KEY")
        with patch.object(frappe, "get_single", return_value=settings), \
             patch.object(frappe, "get_all", side_effect=fake_get_all), \
             patch.object(rp, "_claim_for_polling",
                          side_effect=lambda rows, now: order.append(("claim", [r.name for r in rows]))), \
             patch.object(rp, "_reconcile_one",
                          side_effect=lambda req, *a: order.append(("poll", req.name))), \
             patch.object(frappe.db, "set_value"), \
             patch.object(frappe.db, "get_value", return_value=None), \
             patch.object(frappe.db, "commit"):
            rp.reconcile_pending_payments()

        # One claim, covering BOTH sweeps, and it lands before the first lookup.
        self.assertEqual(order[0], ("claim", ["IPREQ-1", "IPREQ-2", "IPREQ-OLD"]))
        self.assertEqual(
            order[1:],
            [("poll", "IPREQ-1"), ("poll", "IPREQ-2"), ("poll", "IPREQ-OLD")],
        )

    def test_the_claim_is_committed_before_any_lookup_runs(self):
        """_search_transaction raises on an errored lookup by design and the sweep rolls
        back on that, so a stamp written after the lookup would be undone — and an
        erroring request would be re-queried every run, which is the pause's complaint."""
        order = []
        with patch.object(frappe.db, "set_value", side_effect=lambda *a, **kw: order.append("stamp")), \
             patch.object(frappe.db, "commit", side_effect=lambda: order.append("commit")):
            rp._claim_for_polling([_row("IPREQ-1")], frappe.utils.now_datetime())
        self.assertEqual(order, ["stamp", "commit"])


class TestSweepSelection(FrappeTestCase):
    """What one run actually asks the database for."""

    def _run_and_capture(self, active_rows, stale_rows=()):
        captured = []

        def fake_get_all(doctype, **kwargs):
            captured.append(kwargs)
            in_window = kwargs["filters"]["creation"][0] == ">"
            rows = active_rows if in_window else stale_rows
            return list(rows)[: kwargs["limit_page_length"]]

        settings = frappe._dict(vendor_id="VID", api_key="KEY")
        with patch.object(frappe, "get_single", return_value=settings), \
             patch.object(frappe, "get_all", side_effect=fake_get_all), \
             patch.object(rp, "_claim_for_polling"), \
             patch.object(rp, "_reconcile_one"), \
             patch.object(frappe.db, "set_value"), \
             patch.object(frappe.db, "get_value", return_value=None), \
             patch.object(frappe.db, "commit"):
            rp.reconcile_pending_payments()
        return captured

    def test_both_sweeps_are_due_gated(self):
        captured = self._run_and_capture([_row("IPREQ-1")], [_row("IPREQ-2")])
        self.assertEqual(len(captured), 2)
        for kwargs in captured:
            with self.subTest(filters=kwargs["filters"]):
                self.assertEqual(
                    [c[0] for c in kwargs["or_filters"]], ["next_poll_at", "next_poll_at"]
                )

    def test_the_longest_overdue_request_goes_first(self):
        for kwargs in self._run_and_capture([_row("IPREQ-1")], [_row("IPREQ-2")]):
            with self.subTest(filters=kwargs["filters"]):
                self.assertEqual(kwargs["order_by"], "next_poll_at asc")

    def test_one_run_is_capped_at_the_batch_size(self):
        # More due requests than a run may look up: the rest wait for the next run rather
        # than making the run outlast the 5-minute interval it is scheduled on.
        many = [_row(f"IPREQ-{i}") for i in range(rp.RECONCILE_BATCH_SIZE * 3)]
        captured = self._run_and_capture(many, many)
        self.assertEqual(captured[0]["limit_page_length"], rp.RECONCILE_BATCH_SIZE)
        # The active sweep filled the budget, so the stale sweep is not run at all.
        self.assertEqual(len(captured), 1)

    def test_the_two_sweeps_share_one_budget(self):
        active = [_row(f"IPREQ-{i}") for i in range(4)]
        captured = self._run_and_capture(active, [_row("IPREQ-OLD")])
        self.assertEqual(captured[1]["limit_page_length"], rp.RECONCILE_BATCH_SIZE - 4)

    def test_a_full_active_sweep_never_asks_for_an_unlimited_stale_sweep(self):
        """frappe reads limit_page_length=0 as 'no limit', so a zero remaining budget must
        skip the query rather than pass the zero through."""
        many = [_row(f"IPREQ-{i}") for i in range(rp.RECONCILE_BATCH_SIZE)]
        for kwargs in self._run_and_capture(many, many):
            with self.subTest(filters=kwargs["filters"]):
                self.assertTrue(kwargs["limit_page_length"])

    def test_a_cancelled_request_is_never_polled(self):
        # The negative persona. The due gate is an OR group, and an OR evaluated at the top
        # level would leak docstatus 2 into a charge-adjacent path; docstatus must stay an
        # AND-ed filter, never one of the or_filters.
        for kwargs in self._run_and_capture([_row("IPREQ-1")], [_row("IPREQ-2")]):
            with self.subTest(filters=kwargs["filters"]):
                self.assertEqual(kwargs["filters"]["docstatus"], 1)
                self.assertNotIn("docstatus", [c[0] for c in kwargs["or_filters"]])

    def test_only_undelivered_requests_are_polled(self):
        for kwargs in self._run_and_capture([_row("IPREQ-1")], [_row("IPREQ-2")]):
            with self.subTest(filters=kwargs["filters"]):
                self.assertEqual(kwargs["filters"]["callback_delivered"], 0)

    def test_the_attempt_count_is_fetched_so_the_next_delay_can_be_derived(self):
        for kwargs in self._run_and_capture([_row("IPREQ-1")], [_row("IPREQ-2")]):
            with self.subTest(filters=kwargs["filters"]):
                self.assertIn("poll_attempts", kwargs["fields"])


class TestTheBackstopIsActuallyOn(FrappeTestCase):
    """A perfect schedule is worthless if nothing calls it. This is the regression test for
    the state this change fixes: paused function plus commented-out cron."""

    def test_the_sweep_is_not_paused(self):
        self.assertFalse(rp.RECONCILE_PAUSED)

    def test_the_cron_is_registered_and_points_at_the_sweep(self):
        from ipay import hooks

        cron = hooks.scheduler_events.get("cron", {})
        methods = [m for entries in cron.values() for m in entries]
        self.assertIn(
            "ipay.ipay.main.utils.reconcile_payments.reconcile_pending_payments", methods
        )

    def test_the_paused_flag_still_short_circuits_the_sweep(self):
        # Kept as a kill switch: an external paid dependency must be stoppable without a
        # deploy, and an existing guard test in test_payment_guards keys off this flag.
        with patch.object(rp, "RECONCILE_PAUSED", True), \
             patch.object(frappe, "get_single") as get_single:
            rp.reconcile_pending_payments()
        self.assertFalse(get_single.called)


class TestVerificationTimeoutIsRecoverable(FrappeTestCase):
    """A customer slower than the in-session verify window used to end up with a payment
    nobody would finish and a request the guards still allowed charging again."""

    def _lipana_with_timed_out_verification(self):
        state = frappe._dict(docstatus=1, status="Pending")
        with patch.object(main, "verify_mpesa_payment", return_value=None) as verify, \
             patch.object(main, "get_sid", return_value={"data": {"sid": "SID"}}), \
             patch.object(main, "trigger_stk_push", return_value={"header_status": 200}), \
             patch.object(main, "finalize_payment") as finalize, \
             patch.object(main, "create_log_entry"), \
             patch.object(rd, "_request_awaits_cheque", return_value=False), \
             patch.object(frappe, "get_doc", return_value=frappe._dict(vendor_id="VID", api_key="KEY")), \
             patch.object(frappe.db, "get_value", return_value=state), \
             patch.object(frappe.db, "get_single_value", return_value=0), \
             patch.object(frappe.db, "set_value") as set_value, \
             patch.object(frappe.db, "commit"), \
             patch.object(frappe.local, "request", None):
            main.lipana_mpesa(
                docid="IPREQ-1", user_id="u", phone="254712345678", amount=100,
                oid="SINV-1", customer_email="c@example.com",
                payment_request_type="Mpesa Express",
            )
        return verify, finalize, set_value

    def test_verification_timeout_does_not_leave_a_chargeable_pending(self):
        verify, finalize, set_value = self._lipana_with_timed_out_verification()
        self.assertTrue(verify.called)
        # Nothing is finalised in session — there is nothing to finalise yet.
        self.assertFalse(finalize.called)
        # Crucially it is NOT marked Failed: that reads as "the customer did not pay" and
        # is what invited the second charge. It stays Pending, which the backstop owns.
        statuses = [
            call.args[2] for call in set_value.call_args_list
            if len(call.args) > 2 and isinstance(call.args[2], str)
        ]
        self.assertNotIn("Failed", statuses)
        # And the recovery it is handed to is real: enabled, scheduled, and it treats a
        # request it has never stamped as due.
        self.assertFalse(rp.RECONCILE_PAUSED)
        self.assertIn(
            ["next_poll_at", "is", "not set"],
            rp._due_or_filters(frappe.utils.now_datetime()),
        )

    def test_a_finalised_timeout_recovery_leaves_the_request_unchargeable(self):
        # Once the backstop finalises it, the status must be one the charge guards refuse,
        # so the reuse path in ipay_redirect cannot hand it out for a second charge.
        for status in ("Success", "Underpaid", "Overpaid", "Received"):
            with self.subTest(status=status):
                self.assertIn(status, MONEY_ARRIVED)


class TestMoneyAtRiskReachesAccounts(FrappeTestCase):
    """Money confirmed at iPay that cannot be posted must reach a human who can fix it."""

    def _finalize_with_a_failing_ledger_write(self):
        defaults = frappe._dict(
            sales_invoice="SINV-1", amount=100, customer="C-1",
            customer_email="c@example.com", docstatus=1,
        )
        data = {
            "transaction_code": "ABC123", "transaction_amount": 100,
            "firstname": "Mary", "telephone": "254712345678",
            "paid_at": "2026-09-11 12:00:00",
        }
        with patch.object(fp, "make_payment_entry", return_value={"status": "error", "message": "boom"}), \
             patch.object(fp, "notify_collection_error") as collector, \
             patch.object(fp, "notify_money_at_risk") as accounts, \
             patch.object(frappe.db, "get_value", return_value=defaults), \
             patch.object(frappe.db, "set_value"), \
             patch.object(frappe.db, "commit"):
            result = fp.finalize_payment("IPREQ-1", data)
        return result, collector, accounts

    def test_money_at_risk_is_raised_when_the_ledger_write_fails(self):
        result, collector, accounts = self._finalize_with_a_failing_ledger_write()
        self.assertEqual(result["request_status"], "Received")
        # Both audiences: the collector must not charge again, accounts must reconcile it.
        self.assertTrue(collector.called)
        self.assertTrue(accounts.called)

    def test_the_alert_carries_what_accounts_needs_to_act(self):
        _result, _collector, accounts = self._finalize_with_a_failing_ledger_write()
        subject, message = accounts.call_args.args
        self.assertIn("IPREQ-1", subject)
        for detail in ("ABC123", "Mary", "100", "boom"):
            with self.subTest(detail=detail):
                self.assertIn(detail, message)

    def test_a_successful_payment_raises_no_alert(self):
        # A money-at-risk alert that fires on healthy payments is an alert nobody reads.
        defaults = frappe._dict(
            sales_invoice="SINV-1", amount=100, customer="C-1",
            customer_email="c@example.com", docstatus=1,
        )
        with patch.object(fp, "make_payment_entry", return_value={"status": "success", "allocated": 100}), \
             patch.object(fp, "notify_money_at_risk") as accounts, \
             patch.object(fp, "notify_collection_success"), \
             patch.object(fp, "deliver_callback"), \
             patch.object(frappe.db, "get_value", return_value=defaults), \
             patch.object(frappe.db, "set_value"), \
             patch.object(frappe.db, "commit"):
            fp.finalize_payment("IPREQ-1", {"transaction_code": "ABC123", "transaction_amount": 100})
        self.assertFalse(accounts.called)

    def test_the_sweep_no_longer_sends_its_own_duplicate_alert(self):
        # finalize_payment covers every caller, so a second call here would mean two
        # alerts for one failure.
        self.assertFalse(hasattr(rp, "notify_money_at_risk"))
