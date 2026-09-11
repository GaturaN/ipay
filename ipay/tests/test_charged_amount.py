"""What an M-Pesa prompt charges must be decided by the server, not by its caller.

``lipana_mpesa`` is a whitelisted POST endpoint. The desk dialog sends an ``amount``
field it marks read-only in the browser, and that number used to become both the sum
charged and the sum the arriving payment was graded against — so a request could be
charged for less than the invoice owes and still resolve as a clean "Success".

These tests pin the amount to the invoice's live outstanding, read server-side, on
every path that consumes it: the sum charged, the sum stored on the request, the sum
the payment is graded against, and the M-Pesa ceiling.

The Sales Invoice reads are stubbed per field rather than stubbing the helper, so a
helper that reached for ``grand_total`` instead of ``outstanding_amount`` fails here.
The caller names a different invoice from the one the request covers, and supplies an
amount, for the same reason: deriving from either must fail rather than pass unnoticed.
"""

from contextlib import ExitStack
from inspect import signature
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.ipay.main import main
from ipay.ipay.main.utils import ipay_redirect as rd

REQUEST = "REQ-1"
SALES_INVOICE = "ACC-SINV-0001"
PHONE = "254700000000"
EMAIL = "customer@example.com"

# The invoice the caller names, which is NOT the one the request covers. Deriving from
# this instead of from the request's own invoice is the same class of defect as trusting
# the caller's amount, so it must fail the suite rather than pass unnoticed.
CALLER_INVOICE = "ACC-SINV-CALLER"
CALLER_INVOICE_OUTSTANDING = 7

# What the caller asks for. Every assertion below is that this number is ignored.
CALLER_AMOUNT = 1

# What the invoice actually owes. Deliberately far from CALLER_AMOUNT so a partial
# read or a silent fallback cannot coincidentally produce the right answer.
OUTSTANDING = 50000

# A part-paid invoice: the original total still reads 50,000 while only 20,000 is
# owed. Charging the total here would overcharge a customer who has already paid.
PART_PAID_OUTSTANDING = 20000
PART_PAID_TOTAL = 50000

# A two-invoice bundle whose float sum is 0.30000000000000004, not 0.3.
BUNDLE = {"ACC-SINV-0002": 0.1, "ACC-SINV-0003": 0.2}

MPESA_CAP = 250000

PAYBILL_CHANNELS = {"account": "ACC", "payment_channels": [{"name": "MPESA", "paybill": "123"}]}


def _get_value(outstanding, total=None, status="Pending", docstatus=1):
    """Stub frappe.db.get_value per (doctype, field) so the real amount lookup runs.

    ``outstanding`` is either what the request's own invoice owes, or a mapping of
    invoice name to amount for a bundle. Any invoice not named in it owes something
    else entirely, so charging the wrong invoice cannot produce the right total.
    """
    owed = outstanding if isinstance(outstanding, dict) else {SALES_INVOICE: outstanding}

    def _lookup(doctype, name, fieldname=None, **kwargs):
        if doctype == "iPay Request" and fieldname == ["docstatus", "status"]:
            return frappe._dict(docstatus=docstatus, status=status)
        if doctype == "iPay Request" and fieldname == "sales_invoice":
            return SALES_INVOICE
        if doctype == "Sales Invoice" and fieldname == "outstanding_amount":
            return owed.get(name, CALLER_INVOICE_OUTSTANDING)
        if doctype == "Sales Invoice" and fieldname == "grand_total":
            return total
        raise AssertionError(f"unexpected get_value({doctype}, {name}, {fieldname})")

    return _lookup


class _Charged(BaseException):
    """Carries the amount handed to the gateway, stopping the flow at the charge.

    Not an Exception: lipana_mpesa's own error handling would otherwise catch this
    sentinel and report a failed collection instead of letting the test read it.
    """

    def __init__(self, amount):
        super().__init__(f"charged {amount}")
        self.amount = amount


def _capture_charge(*args, **kwargs):
    raise _Charged(args[2])


class ChargedAmountTestCase(FrappeTestCase):
    """Shared harness: run lipana_mpesa far enough to see what it would charge."""

    def setUp(self):
        self.stored = {}

    def _record(self, doctype, name, fieldname, value=None, **kwargs):
        self.stored.update(fieldname if isinstance(fieldname, dict) else {fieldname: value})

    def _prompt(self, outstanding, total=None, request_type="Mpesa Express", bundle=(),
                amount=None, **gateway):
        """Call the endpoint as the enqueued worker does, with the gateway stubbed.

        ``bundle`` names the request's child invoice rows; empty means a single-invoice
        request, which falls back to the invoice recorded on the request itself.
        """
        settings = frappe._dict(vendor_id="VID", api_key="KEY")
        patches = [
            patch.object(frappe.local, "request", None, create=True),
            patch.object(frappe.db, "get_value", side_effect=_get_value(outstanding, total)),
            patch.object(frappe.db, "set_value", side_effect=self._record),
            patch.object(frappe.db, "commit"),
            patch.object(frappe.db, "get_single_value", return_value=MPESA_CAP),
            patch.object(frappe, "get_doc", return_value=settings),
            # frappe.msgprint is deliberately unstubbed: frappe.throw raises through it.
            patch.object(frappe, "get_all", return_value=list(bundle)),
            patch.object(rd, "_request_awaits_cheque", return_value=False),
            patch.object(main, "create_log_entry"),
        ]
        for name, stub in {"get_sid": _capture_charge, **gateway}.items():
            patches.append(patch.object(main, name, side_effect=stub))
        with ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            return main.lipana_mpesa(
                REQUEST, EMAIL, PHONE, CALLER_INVOICE, EMAIL, request_type, amount=amount,
            )

    def _charge(self, **kwargs):
        with self.assertRaises(_Charged) as caught:
            self._prompt(**kwargs)
        return caught.exception.amount


class TestChargedAmountIsServerDerived(ChargedAmountTestCase):
    def test_the_charged_amount_is_the_live_outstanding_not_the_argument(self):
        self.assertEqual(self._charge(outstanding=OUTSTANDING), OUTSTANDING)

    def test_the_stored_amount_is_the_live_outstanding_not_the_argument(self):
        # Stored because every later finaliser grades the payment against this field.
        self._charge(outstanding=OUTSTANDING)
        self.assertEqual(self.stored["amount"], OUTSTANDING)

    def test_a_part_paid_invoice_is_charged_what_is_left_not_its_total(self):
        charged = self._charge(outstanding=PART_PAID_OUTSTANDING, total=PART_PAID_TOTAL)
        self.assertEqual(charged, PART_PAID_OUTSTANDING)
        self.assertEqual(self.stored["amount"], PART_PAID_OUTSTANDING)

    def test_the_paybill_details_quote_the_live_outstanding_to_the_cent(self):
        # The Paybill branch hands the amount back for the customer to key in by hand,
        # so it must read as money — never a float artefact from summing a bundle.
        _, _, quoted = self._prompt(
            outstanding=OUTSTANDING,
            request_type="Mpesa Paybill",
            get_sid=lambda *a, **k: {"data": PAYBILL_CHANNELS},
        )
        self.assertEqual(quoted, f"{OUTSTANDING:.2f}")

    def test_a_bundle_is_charged_the_sum_of_its_invoices_rounded_to_the_cent(self):
        # Summing in float gives 0.30000000000000004, which get_sid would hash and charge
        # verbatim. Also the only coverage of the bundle's child-row path.
        self.assertEqual(self._charge(outstanding=BUNDLE, bundle=tuple(BUNDLE)), 0.3)


class TestASuppliedAmountIsInert(ChargedAmountTestCase):
    """``amount`` is still accepted, for one release, so jobs enqueued by the previous
    release survive the deploy — RQ passes their kwargs through unfiltered.

    It must change nothing. These are the tests that stop it quietly becoming live again.
    """

    def test_a_supplied_amount_does_not_change_what_is_charged(self):
        self.assertEqual(self._charge(outstanding=OUTSTANDING, amount=CALLER_AMOUNT), OUTSTANDING)

    def test_a_supplied_amount_does_not_change_what_is_stored(self):
        self._charge(outstanding=OUTSTANDING, amount=CALLER_AMOUNT)
        self.assertEqual(self.stored["amount"], OUTSTANDING)

    def test_the_parameter_is_optional_so_this_release_can_stop_sending_it(self):
        self.assertIsNone(signature(main.lipana_mpesa).parameters["amount"].default)


class TestGradingUsesTheServerAmount(ChargedAmountTestCase):
    """The sum a payment is graded against must be the sum that was charged."""

    def test_finalise_grades_against_the_live_outstanding_not_the_argument(self):
        graded = {}

        def _finalize(request_name, data, expected_amount=None, **kwargs):
            graded["expected"] = expected_amount
            return {"status": "success", "response_data": {}, "payment_entry": "PE-1"}

        self._prompt(
            outstanding=OUTSTANDING,
            amount=CALLER_AMOUNT,
            get_sid=lambda *a, **k: {"data": {"sid": "SID"}},
            trigger_stk_push=lambda *a, **k: {"header_status": 200},
            verify_mpesa_payment=lambda *a, **k: {"data": {}},
            finalize_payment=_finalize,
        )
        self.assertEqual(graded["expected"], OUTSTANDING)


class TestServerAmountIsGuarded(ChargedAmountTestCase):
    """The derived amount is what the ceiling and the nothing-left check must see."""

    def test_the_mpesa_ceiling_is_applied_to_the_live_outstanding(self):
        # A caller-supplied 1 must not walk an over-ceiling charge past the cap.
        with self.assertRaises(frappe.ValidationError):
            self._prompt(outstanding=MPESA_CAP + 1)

    def test_a_settled_invoice_is_not_charged(self):
        self.assertEqual(self._prompt(outstanding=0)["status"], "skipped")
