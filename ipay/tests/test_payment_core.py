from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main.utils import reconcile_payments
from ipay.ipay.main.utils.constants import amounts_match, clean_oid
from ipay.ipay.main.utils.finalize_payment import _resolve_status
from ipay.ipay.main.utils.ipay_redirect import normalize_phone


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
