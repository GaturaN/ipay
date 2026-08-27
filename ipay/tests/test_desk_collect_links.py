import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.www import collect_payments as cp

WORKSPACE = frappe.get_app_path("ipay", "ipay", "workspace", "ipay", "ipay.json")

# The dashboard button is a URL shortcut pointing at the existing role-aware redirect.
SHORTCUT_LABEL = "Collect Payments"
SHORTCUT_URL = "/collect_payments"

# `modified` shipped by PR #108. Frappe re-imports a fixture on a content-hash change, but
# this repo also bumps the timestamp so the older timestamp gate agrees; a fixture edit that
# forgets the bump fails here.
PREVIOUS_MODIFIED = "2026-08-19 14:00:00.000000"

# What the dashboard holds, so dropping a card or a chart while editing the fixture fails
# loudly instead of silently shipping a thinner dashboard.
WIDGET_COUNTS = {
    "number_cards": 10,
    "charts": 3,
    "quick_lists": 2,
    "shortcuts": 7,
    "links": 13,
}

# A content block names its widget by the child row's `label`, not by the widget's document
# name (see PR #108: the 'Total Outstanding' card is named 'iPay Outstanding to Collect').
BLOCK_TO_TABLE = {
    "number_card": ("number_card_name", "number_cards"),
    "chart": ("chart_name", "charts"),
    "quick_list": ("quick_list_name", "quick_lists"),
    "shortcut": ("shortcut_name", "shortcuts"),
    "card": ("card_name", "links"),
}


def _workspace():
    raw = open(WORKSPACE).read()
    return raw, json.loads(raw)


class TestCollectPaymentsRouting(FrappeTestCase):
    """The dashboard button is a plain link to /collect_payments, so the whole "take them to
    the right page for who they are" promise rests on this redirect. It had no test."""

    def _redirect_for(self, roles, user="staff@example.com"):
        frappe.local.flags.redirect_location = None
        with patch.dict(frappe.session, {"user": user}), \
             patch.object(frappe, "get_roles", return_value=list(roles)):
            with self.assertRaises(frappe.Redirect):
                cp.get_context(frappe._dict())
        return frappe.local.flags.redirect_location

    def test_a_sales_member_lands_on_their_own_book(self):
        self.assertEqual(self._redirect_for(["Sales User"]), "/collect/sales")

    def test_a_sales_manager_lands_on_the_sales_page(self):
        self.assertEqual(self._redirect_for(["Sales Manager"]), "/collect/sales")

    def test_a_collector_lands_on_the_field_page(self):
        self.assertEqual(self._redirect_for(["iPay Collector"]), "/collect")

    def test_an_operator_lands_on_internal(self):
        for role in ("System Manager", "iPay Manager", "iPay User"):
            with self.subTest(role=role):
                self.assertEqual(self._redirect_for([role]), "/collect/internal")

    def test_an_operator_who_also_sells_still_lands_on_internal(self):
        # The operator role wins: internal mode carries every book plus the member filter.
        self.assertEqual(self._redirect_for(["iPay User", "Sales User"]), "/collect/internal")

    def test_a_collector_who_is_also_an_operator_is_not_scoped_to_the_field_page(self):
        self.assertEqual(self._redirect_for(["iPay Collector", "iPay User"]), "/collect/internal")

    def test_a_guest_is_sent_to_log_in_and_back_here_so_the_role_branch_reruns(self):
        frappe.local.flags.redirect_location = None
        with patch.dict(frappe.session, {"user": "Guest"}):
            with self.assertRaises(frappe.Redirect):
                cp.get_context(frappe._dict())
        self.assertEqual(
            frappe.local.flags.redirect_location, "/login?redirect-to=/collect_payments"
        )

    def test_a_desk_user_with_no_ipay_role_is_refused_rather_than_redirected(self):
        # Frappe does not permission-filter URL shortcuts, so non-iPay staff will see the
        # dashboard button. They must get a clear refusal, never a redirect into a page that
        # would then refuse them anyway.
        frappe.local.flags.redirect_location = None
        with patch.dict(frappe.session, {"user": "stock@example.com"}), \
             patch.object(frappe, "get_roles", return_value=["Stock User"]):
            with self.assertRaises(frappe.PermissionError):
                cp.get_context(frappe._dict())
        self.assertIsNone(frappe.local.flags.redirect_location)


class TestDashboardCollectShortcut(FrappeTestCase):
    """The desk entry point is a fixture, not code — it only reaches a site through
    `bench migrate`. These assertions stand in for the unit test a fixture cannot have."""

    def test_the_shortcut_targets_the_role_aware_redirect(self):
        _, doc = _workspace()
        rows = [s for s in doc["shortcuts"] if s["label"] == SHORTCUT_LABEL]
        self.assertEqual(len(rows), 1, "expected exactly one Collect Payments shortcut")
        self.assertEqual(rows[0]["type"], "URL")
        self.assertEqual(rows[0]["url"], SHORTCUT_URL)

    def test_the_button_is_placed_above_the_dashboard_figures(self):
        # Discoverability is the point of the change: it must not be buried under the cards.
        _, doc = _workspace()
        blocks = json.loads(doc["content"])
        button = next(
            i
            for i, b in enumerate(blocks)
            if b["type"] == "shortcut" and b["data"]["shortcut_name"] == SHORTCUT_LABEL
        )
        first_card = next(i for i, b in enumerate(blocks) if b["type"] == "number_card")
        self.assertLess(button, first_card)

    def test_every_content_block_resolves_to_a_widget_that_exists(self):
        # A block naming a widget that is not in its child table renders blank on the desk.
        _, doc = _workspace()
        for block in json.loads(doc["content"]):
            if block["type"] not in BLOCK_TO_TABLE:
                continue
            key, table = BLOCK_TO_TABLE[block["type"]]
            labels = {row["label"] for row in doc[table]}
            with self.subTest(block=block["id"]):
                self.assertIn(block["data"][key], labels)

    def test_block_ids_are_unique(self):
        _, doc = _workspace()
        ids = [b["id"] for b in json.loads(doc["content"])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_nothing_else_was_dropped_from_the_dashboard(self):
        _, doc = _workspace()
        self.assertEqual({k: len(doc[k]) for k in WIDGET_COUNTS}, WIDGET_COUNTS)

    def test_modified_was_bumped_so_the_fixture_re_imports(self):
        _, doc = _workspace()
        self.assertGreater(doc["modified"], PREVIOUS_MODIFIED)

    def test_the_file_is_still_in_frappe_export_format(self):
        # Frappe writes these with indent=1 and sorted keys. Keeping the file canonical is
        # what makes a structural diff of it trustworthy.
        raw, doc = _workspace()
        self.assertEqual(json.dumps(doc, indent=1, sort_keys=True) + "\n", raw)
