from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main.utils import cheque, make_payment_entry, reconcile_payments
from ipay.ipay.main.utils.constants import amounts_match, clean_oid
from ipay.ipay.main.utils.finalize_payment import _resolve_status
from ipay.ipay.main.utils.ipay_redirect import normalize_phone
from ipay.ipay.main.utils.make_payment_entry import allocate_references


class TestNormalizePhone(FrappeTestCase):
    """A wrong number charges the wrong phone, so normalisation is money-critical."""

    def test_local_zero_prefix_becomes_msisdn(self):
        self.assertEqual(normalize_phone("0712345678"), "254712345678")
        self.assertEqual(normalize_phone("0112345678"), "254112345678")

    def test_bare_nine_digit_gets_country_code(self):
        self.assertEqual(normalize_phone("712345678"), "254712345678")
        self.assertEqual(normalize_phone("112345678"), "254112345678")

    def test_already_msisdn_is_unchanged(self):
        self.assertEqual(normalize_phone("254712345678"), "254712345678")

    def test_separators_and_plus_are_stripped(self):
        self.assertEqual(normalize_phone("+254 712 345 678"), "254712345678")
        self.assertEqual(normalize_phone("0712-345-678"), "254712345678")

    def test_junk_returns_empty_so_caller_prompts(self):
        self.assertEqual(normalize_phone("0812345678"), "")  # 08 is not a mobile prefix
        self.assertEqual(normalize_phone("0712"), "")  # too short
        self.assertEqual(normalize_phone("254712345678999"), "")  # too long
        self.assertEqual(normalize_phone("not a phone"), "")
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(None), "")


class TestAmountsMatch(FrappeTestCase):
    """Amount matching decides Success vs Under/Overpaid — it must be cent-exact."""

    def test_equal_amounts_match(self):
        self.assertTrue(amounts_match(100, 100))
        self.assertTrue(amounts_match("100", 100))

    def test_within_a_cent_matches(self):
        self.assertTrue(amounts_match(100.00, 100.005))

    def test_over_a_cent_does_not_match(self):
        self.assertFalse(amounts_match(100, 101))
        self.assertFalse(amounts_match(99.98, 100))

    def test_non_numeric_is_not_a_match(self):
        self.assertFalse(amounts_match(None, 100))
        self.assertFalse(amounts_match("abc", 100))


class TestResolveStatus(FrappeTestCase):
    """Classifying a recorded payment: Success / Underpaid / Overpaid."""

    def test_full_amount_allocated_is_success(self):
        self.assertEqual(_resolve_status({"allocated": 100}, 100, 100), "Success")

    def test_less_than_expected_is_underpaid(self):
        self.assertEqual(_resolve_status({"allocated": 70}, 70, 100), "Underpaid")

    def test_more_than_expected_is_overpaid(self):
        self.assertEqual(_resolve_status({"allocated": 100}, 120, 100), "Overpaid")

    def test_exact_amount_but_nothing_allocated_is_overpaid(self):
        self.assertEqual(_resolve_status({"allocated": 0}, 100, 100), "Overpaid")


class TestCleanOid(FrappeTestCase):
    """The iPay order id must drop characters iPay rejects."""

    def test_unwanted_characters_are_stripped(self):
        self.assertEqual(clean_oid("ACC-SINV-2024-00001"), "ACCSINV202400001")

    def test_empty_name_is_empty(self):
        self.assertEqual(clean_oid(None), "")


def _allocate(invoices, terms, amount):
    """Run the allocator against fake invoices/terms. `invoices` maps name -> outstanding,
    `terms` maps invoice name -> [(payment_term, term_outstanding), ...]."""
    rows = {
        name: frappe._dict(
            name=name, outstanding_amount=out, posting_date="2026-01-01",
            customer="C", customer_name="C", company="Co",
        )
        for name, out in invoices.items()
    }
    with patch.object(make_payment_entry.frappe.db, "get_value", side_effect=lambda dt, n, f, **k: rows[n]):
        with patch.object(
            make_payment_entry.frappe,
            "get_all",
            side_effect=lambda dt, **k: [
                frappe._dict(payment_term=t, outstanding=o)
                for t, o in terms.get(k["filters"]["parent"], [])
            ],
        ):
            return allocate_references(list(invoices), amount)


class TestAllocateReferences(FrappeTestCase):
    """Allocation decides which invoice a payment clears. Over-allocate and ERPNext rejects the
    whole entry — the customer's money is taken and no Payment Entry exists."""

    def test_term_outstanding_never_exceeds_the_invoice(self):
        # ERPNext only decrements a term row when the payment names its payment_term, so the row
        # can claim far more than the invoice still owes. The invoice is the truth.
        _, refs, remaining = _allocate({"INV-1": 3229.8}, {"INV-1": [("NET 15", 249952.0)]}, 53229.8)
        self.assertEqual(sum(r["allocated_amount"] for r in refs), 3229.8)
        self.assertEqual(remaining, 50000.0)

    def test_exact_bundle_total_reaches_every_invoice(self):
        # A stale first term used to swallow the whole payment, leaving the rest unpaid.
        _, refs, remaining = _allocate(
            {"INV-1": 3229.8, "INV-2": 22088.0},
            {"INV-1": [("NET 15", 249952.0)], "INV-2": [("NET 15", 22088.0)]},
            25317.8,
        )
        allocated = {r["reference_name"]: r["allocated_amount"] for r in refs}
        self.assertEqual(allocated, {"INV-1": 3229.8, "INV-2": 22088.0})
        self.assertEqual(remaining, 0.0)

    def test_partial_payment_fills_each_term_before_the_next(self):
        # Due-date order is the DB's job (order_by on the query), so it is not asserted here.
        _, refs, remaining = _allocate(
            {"INV-1": 1000.0}, {"INV-1": [("First", 400.0), ("Second", 600.0)]}, 500.0
        )
        self.assertEqual(
            [(r["payment_term"], r["allocated_amount"]) for r in refs],
            [("First", 400.0), ("Second", 100.0)],
        )
        self.assertEqual(remaining, 0.0)

    def test_invoice_without_terms_takes_one_reference(self):
        _, refs, remaining = _allocate({"INV-1": 800.0}, {}, 1000.0)
        self.assertEqual(refs, [
            {"reference_doctype": "Sales Invoice", "reference_name": "INV-1", "allocated_amount": 800.0}
        ])
        self.assertEqual(remaining, 200.0)

    def test_settled_invoice_is_skipped_and_money_stays_credit(self):
        _, refs, remaining = _allocate({"INV-1": 0.0}, {"INV-1": [("NET 15", 5000.0)]}, 700.0)
        self.assertEqual(refs, [])
        self.assertEqual(remaining, 700.0)


def _awaiting(entries, ask=None):
    """Run the cheque predicate against fake Payment Entries.

    `entries` is [(parent, docstatus, mode, [(invoice, amount), ...]), ...]. The mock applies the
    real filters, so dropping one in the code makes these tests fail rather than pass regardless."""
    def get_all(doctype, **kwargs):
        filters = kwargs["filters"]
        if doctype == "Payment Entry Reference":
            return [
                frappe._dict(parent=parent, reference_name=inv, allocated_amount=amount)
                for parent, docstatus, _mode, refs in entries
                for inv, amount in refs
                if docstatus == filters["docstatus"]
                and filters["reference_doctype"] == "Sales Invoice"
                and inv in filters["reference_name"][1]
            ]
        return [
            parent
            for parent, docstatus, mode, _refs in entries
            if parent in filters["name"][1]
            and docstatus == filters["docstatus"]
            and mode == filters["mode_of_payment"]
        ]

    invoices = ask or [inv for _, _, _, refs in entries for inv, _ in refs]
    with patch.object(cheque.frappe, "get_all", side_effect=get_all):
        return cheque.awaiting_cheque_amounts(invoices)


DRAFT, SUBMITTED = 0, 1


class TestAwaitingChequeAmounts(FrappeTestCase):
    """What this returns decides whether an invoice can be charged again. A false negative
    collects the money twice; a false positive strands an invoice nobody can collect."""

    def test_no_invoices_asks_nothing(self):
        self.assertEqual(cheque.awaiting_cheque_amounts([]), {})
        self.assertEqual(cheque.awaiting_cheque_amounts(None), {})

    def test_draft_cheque_covers_its_invoice(self):
        covered = _awaiting([("PE-1", DRAFT, "Cheque", [("INV-1", 700.0)])])
        self.assertEqual(covered, {"INV-1": 700.0})

    def test_a_draft_of_another_mode_does_not_count(self):
        # Only the parent knows the mode; an M-Pesa draft must never strand an invoice.
        covered = _awaiting([("PE-1", DRAFT, "MPESA", [("INV-1", 700.0)])], ask=["INV-1"])
        self.assertEqual(covered, {})

    def test_a_submitted_cheque_does_not_count(self):
        # Once accounts submit it, outstanding drops on its own and the marker must let go.
        covered = _awaiting([("PE-1", SUBMITTED, "Cheque", [("INV-1", 700.0)])], ask=["INV-1"])
        self.assertEqual(covered, {})

    def test_several_cheques_on_one_invoice_are_summed(self):
        covered = _awaiting([
            ("PE-1", DRAFT, "Cheque", [("INV-1", 700.0)]),
            ("PE-2", DRAFT, "Cheque", [("INV-1", 300.0)]),
        ])
        self.assertEqual(covered, {"INV-1": 1000.0})

    def test_only_the_covered_invoice_is_flagged(self):
        covered = _awaiting([
            ("PE-1", DRAFT, "Cheque", [("INV-1", 700.0)]),
            ("PE-2", DRAFT, "MPESA", [("INV-2", 50.0)]),
        ])
        self.assertEqual(covered, {"INV-1": 700.0})


def _fake_response(status_code, json_value=None, json_error=False):
    resp = MagicMock()
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(str(status_code))
    else:
        resp.raise_for_status.return_value = None
    if json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_value or {}
    return resp


class TestSearchTransaction(FrappeTestCase):
    """A transient iPay error must never read as 'not paid' — that would abandon a
    genuinely-paid request and lose the money."""

    def _search(self):
        return reconcile_payments._search_transaction("OID", "vid", "key")

    def test_404_is_the_only_not_paid_signal(self):
        with patch.object(reconcile_payments.requests, "post", return_value=_fake_response(404)):
            self.assertIsNone(self._search())

    def test_server_error_raises_not_abandons(self):
        with patch.object(reconcile_payments.requests, "post", return_value=_fake_response(502)):
            with self.assertRaises(requests.RequestException):
                self._search()

    def test_non_json_body_raises_not_abandons(self):
        with patch.object(
            reconcile_payments.requests, "post", return_value=_fake_response(200, json_error=True)
        ):
            with self.assertRaises(requests.RequestException):
                self._search()

    def test_paid_transaction_returns_data(self):
        paid = {"data": {"transaction_code": "ABC123", "transaction_amount": "100"}}
        with patch.object(
            reconcile_payments.requests, "post", return_value=_fake_response(200, paid)
        ):
            self.assertEqual(self._search()["transaction_code"], "ABC123")

    def test_record_without_code_is_not_paid(self):
        with patch.object(
            reconcile_payments.requests, "post", return_value=_fake_response(200, {"data": {}})
        ):
            self.assertIsNone(self._search())
