import json
import os
import re
import shutil
import subprocess
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from ipay.www import collect_payments as cp

WORKSPACE = frappe.get_app_path("ipay", "ipay", "workspace", "ipay", "ipay.json")


def _number_card(folder):
    return frappe.get_app_path("ipay", "ipay", "number_card", folder, f"{folder}.json")


PENDING_CARD = "iPay Pending Over an Hour"

# Same gate as PREVIOUS_MODIFIED above, for the file that actually holds the cutoff:
# import_file.py:142-144 skips a non-DocType fixture whose stored timestamp is not older,
# so an edit to the expression that forgets to bump `modified` never reaches a site.
PENDING_CARD_MODIFIED = "2026-09-11 12:00:00.000000"

# The dashboard button is a URL shortcut pointing at the existing role-aware redirect.
SHORTCUT_LABEL = "Collect Payments"
SHORTCUT_URL = "/collect_payments"

# `modified` shipped by PR #108. For a Workspace the timestamp is the ONLY re-import gate —
# frappe/modules/import_file.py only reads a migration_hash when doctype == "DocType", and
# otherwise skips the file whenever the stored timestamp is not older. A fixture edit that
# forgets the bump silently never reaches a site, so this is a floor, not a formality.
PREVIOUS_MODIFIED = "2026-08-27 12:00:00.000000"

# What the dashboard holds, so dropping a card or a chart while editing the fixture fails
# loudly instead of silently shipping a thinner dashboard.
WIDGET_COUNTS = {
    "number_cards": 11,
    "charts": 3,
    "quick_lists": 2,
    "shortcuts": 7,
    "links": 13,
}

# ...and what the layout draws. Defining a widget is not the same as placing it: a block can
# be deleted from `content` while its child row survives, which would silently thin the
# dashboard without changing any count above.
BLOCK_COUNTS = {
    "header": 8,
    "number_card": 11,
    "chart": 3,
    "quick_list": 2,
    "shortcut": 7,
    "card": 3,
}

# A content block names its widget by the child row's `label`, not by the widget's document
# name (see PR #108: the 'Total Outstanding' card is named 'iPay Outstanding to Collect').
BLOCK_TO_TABLE = {
    "number_card": ("number_card_name", "number_cards", None),
    "chart": ("chart_name", "charts", None),
    "quick_list": ("quick_list_name", "quick_lists", None),
    "shortcut": ("shortcut_name", "shortcuts", None),
    # A card block draws one Card Break and the Links beneath it, so only the breaks are
    # candidates — matching against every `links` row would accept a plain Link's label.
    "card": ("card_name", "links", "Card Break"),
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
            key, table, row_type = BLOCK_TO_TABLE[block["type"]]
            labels = {
                row["label"]
                for row in doc[table]
                if row_type is None or row.get("type") == row_type
            }
            with self.subTest(block=block["id"]):
                self.assertIn(block["data"][key], labels)

    def test_block_ids_are_unique(self):
        _, doc = _workspace()
        ids = [b["id"] for b in json.loads(doc["content"])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_widget_was_dropped_from_the_dashboard(self):
        _, doc = _workspace()
        self.assertEqual({k: len(doc[k]) for k in WIDGET_COUNTS}, WIDGET_COUNTS)

    def test_no_widget_was_dropped_from_the_layout(self):
        _, doc = _workspace()
        counts = {}
        for block in json.loads(doc["content"]):
            counts[block["type"]] = counts.get(block["type"], 0) + 1
        self.assertEqual(counts, BLOCK_COUNTS)

    def test_modified_is_at_least_the_last_released_bump(self):
        # A floor, not a ratchet: it proves this change bumped the timestamp, and stops a
        # later edit from winding it backwards. It cannot see a later edit that forgets to
        # bump at all — nothing in a single file's contents can.
        _, doc = _workspace()
        self.assertGreater(doc["modified"], PREVIOUS_MODIFIED)

    def test_the_file_is_still_in_frappe_export_format(self):
        # frappe.as_json: indent=1, sorted keys. Keeping the file canonical is what makes a
        # structural diff of it trustworthy. The trailing newline is not compared: the repo's
        # copy has one, but frappe/modules/export_file.py writes none, so a file re-exported
        # from the desk would differ only by that.
        raw, doc = _workspace()
        self.assertEqual(frappe.as_json(doc), raw.rstrip("\n"))


class TestPendingOverAnHourCard(FrappeTestCase):
    """Money can leave a customer and never reach the books: the request stays at the
    `Pending` every request is born in, and the reconcile backstop that would have
    resolved it is off (reconcile_payments.py:13 RECONCILE_PAUSED).

    These assertions are structural. They prove what the fixtures say — that no surface
    already on this workspace bounds `Pending` by age, and that this card does, in the
    right section, in the shape that will migrate. They do NOT execute the count: that
    needs a site. The one piece of JavaScript here is exercised separately by
    test_the_cutoff_expression_really_resolves_to_one_hour_ago, which needs node."""

    def _card(self, folder):
        return json.loads(open(_number_card(folder)).read())

    def _age_filter(self):
        """The card's single dynamic filter, as [doctype, field, operator, expression]."""
        card = self._card("ipay_pending_over_an_hour")
        (only,) = json.loads(card["dynamic_filters_json"])
        return only

    def _statuses_matched_by(self, card):
        """The `status` values a Document Type card's static filters admit."""
        matched = set()
        for _doctype, field, operator, value, *_ in json.loads(card["filters_json"]):
            if field != "status":
                continue
            matched |= set(value) if operator == "in" else {value}
        return matched

    def test_no_pre_existing_surface_excluded_pending_was_widened_to_include_it(self):
        # Two of the four surfaces simply omit `Pending` from their status list. Read from
        # the shipped fixtures and the report's own constant, so widening either later
        # makes this fail and be reconsidered rather than silently duplicating the card.
        from ipay.ipay.report.ipay_payments_needing_attention import (
            ipay_payments_needing_attention as attention_report,
        )

        self.assertNotIn("Pending", attention_report.ATTENTION_STATUSES)
        self.assertNotIn(
            "Pending", self._statuses_matched_by(self._card("ipay_undelivered_callbacks"))
        )

        # The two log-backed surfaces key off log_type ERR, and a request going quiet
        # writes no ERR — nothing to filter for. They are blind by construction.
        errors_card = self._card("ipay_errors_today")
        self.assertEqual(errors_card["document_type"], "iPay Logs")
        self.assertIn(["iPay Logs", "log_type", "=", "ERR", False],
                      json.loads(errors_card["filters_json"]))
        _, doc = _workspace()
        errors_list = next(q for q in doc["quick_lists"] if q["label"] == "Errors")
        self.assertEqual(errors_list["document_type"], "iPay Logs")
        self.assertEqual(json.loads(errors_list["quick_list_filter"]), {"log_type": "ERR"})

    def test_the_requests_shortcut_badge_counts_pending_but_bounds_nothing(self):
        # The fifth surface, and the one closest to already doing this job: the iPay
        # Requests shortcut carries a stats_filter, which shortcut_widget.js:91 turns into
        # a live frappe.db.count badge. `status != "Success"` does include Pending — so
        # Pending was never wholly invisible. What that badge cannot do is separate a
        # customer still entering their PIN from money that left days ago: it has no age
        # bound, no docstatus bound, and it pools Pending with Underpaid, Overpaid,
        # Received, Failed and Abandoned. That is why an age-bounded count is still needed.
        _, doc = _workspace()
        requests = next(s for s in doc["shortcuts"] if s["label"] == "iPay Requests")
        terms = json.loads(requests["stats_filter"])
        self.assertEqual(terms, [["iPay Request", "status", "!=", "Success", False]])

        bounded_fields = {t[1] for t in terms}
        self.assertNotIn("creation", bounded_fields, "badge has no age bound")
        self.assertNotIn("docstatus", bounded_fields, "badge counts drafts and cancellations")

    def test_no_shortcut_badge_on_this_workspace_bounds_pending_by_age(self):
        # Generalising the above over every badge rather than only the one we know about,
        # so a stats_filter added later that already answers this question surfaces here.
        _, doc = _workspace()
        for shortcut in doc["shortcuts"]:
            if not shortcut.get("stats_filter"):
                continue
            terms = json.loads(shortcut["stats_filter"])
            with self.subTest(shortcut=shortcut["label"]):
                self.assertNotIn(
                    "creation", {t[1] for t in terms},
                    "a badge bounding creation may already cover this card's job",
                )

    def test_the_status_donut_sees_pending_but_cannot_single_out_a_stranded_one(self):
        # Correcting the audit, which said no surface shows Pending at all. This one does
        # — grouped, proportional, and with no age bound, so a customer still entering
        # their PIN is indistinguishable from money that vanished days ago. That is why a
        # counted, age-bounded card is still needed and why this chart is left alone.
        chart = json.loads(open(frappe.get_app_path(
            "ipay", "ipay", "dashboard_chart", "ipay_requests_by_status",
            "ipay_requests_by_status.json",
        )).read())
        self.assertEqual(chart["chart_type"], "Group By")
        self.assertEqual(chart["group_by_based_on"], "status")

        # Its only bound on age is a month-wide Timespan, and it has no dynamic filter, so
        # it cannot express "older than an hour" however it is read.
        creation_filters = [
            f for f in json.loads(chart["filters_json"]) if f[1] == "creation"
        ]
        self.assertEqual(
            creation_filters, [["iPay Request", "creation", "Timespan", "last month"]]
        )
        self.assertEqual(chart["dynamic_filters_json"], "")

    def test_the_card_counts_submitted_pending_requests_and_nothing_else(self):
        card = self._card("ipay_pending_over_an_hour")
        self.assertEqual(card["document_type"], "iPay Request")
        self.assertEqual(card["function"], "Count")
        self.assertEqual(
            json.loads(card["filters_json"]),
            [
                ["iPay Request", "docstatus", "=", "1", False],
                ["iPay Request", "status", "=", "Pending", False],
            ],
            "a draft or cancelled request is not money in flight and must not be counted",
        )
        self.assertEqual(self._statuses_matched_by(card), {"Pending"})

    def test_the_card_bounds_the_age_so_a_payment_in_flight_is_not_an_alarm(self):
        # Every request starts Pending, so an unbounded count would read as a permanent
        # backlog and be ignored. The direction matters as much as the threshold: `>`
        # here would count every recent request instead of every stale one.
        doctype, field, operator, expression = self._age_filter()
        self.assertEqual((doctype, field, operator), ("iPay Request", "creation", "<"))
        self.assertIn("subtract(1, 'hour')", expression)

    def test_the_cutoff_is_built_from_system_time_not_the_viewers_own(self):
        # `creation` is stored in system tz, but frappe.datetime._date() returns the
        # USER's tz unless asked otherwise — so now_datetime() here would skew the cutoff
        # by each operator's offset and silently show them different numbers.
        expression = self._age_filter()[3]
        self.assertIn("frappe.datetime.system_datetime()", expression)
        self.assertNotIn("now_datetime", expression)

        # And parsed as UTC, not in the viewer's own zone: that string is naive system
        # time, so parsing it locally makes `subtract` a wall-clock operation that lands
        # two hours back for a viewer sitting on their own DST transition.
        self.assertTrue(expression.startswith("moment.utc("), expression)

    def test_the_card_matches_the_shape_of_its_neighbours(self):
        # A fixture only ships if it looks like the ones that already ship: is_standard +
        # module route it through bench migrate, is_public makes it visible to the team.
        new = self._card("ipay_pending_over_an_hour")
        neighbour = self._card("ipay_underpaid_payments")
        for key in ("doctype", "type", "module", "is_standard", "is_public",
                    "stats_time_interval", "show_percentage_stats", "owner", "modified_by"):
            with self.subTest(key=key):
                self.assertEqual(new[key], neighbour[key])
        self.assertEqual(new["name"], new["label"], "autoname derives the docname from label")

    def test_the_card_is_both_registered_and_placed_on_the_dashboard(self):
        # Defining a card is not showing it: it needs a child row AND a content block, and
        # the block resolves the card by the row's label.
        _, doc = _workspace()
        rows = [r for r in doc["number_cards"] if r["label"] == PENDING_CARD]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["number_card_name"], PENDING_CARD)

        blocks = json.loads(doc["content"])
        placed = [
            i for i, b in enumerate(blocks)
            if b["type"] == "number_card" and b["data"]["number_card_name"] == PENDING_CARD
        ]
        self.assertEqual(len(placed), 1)
        self.assertEqual(blocks[placed[0]]["data"]["col"], 3, "same width as its neighbours")

    def test_the_card_sits_under_needs_attention_and_not_somewhere_it_will_be_missed(self):
        # Being on the dashboard is not the point; being in the section the team scans for
        # work is. Anchored to the headers either side rather than to an index.
        _, doc = _workspace()
        blocks = json.loads(doc["content"])
        headers = [
            i for i, b in enumerate(blocks)
            if b["type"] == "header" and "Needs attention" in b["data"]["text"]
        ]
        self.assertEqual(len(headers), 1)
        start = headers[0]
        end = next(i for i, b in enumerate(blocks) if i > start and b["type"] == "header")
        card = next(
            i for i, b in enumerate(blocks)
            if b["type"] == "number_card" and b["data"]["number_card_name"] == PENDING_CARD
        )
        self.assertTrue(start < card < end)

    def test_the_card_file_is_in_frappe_export_format(self):
        # Same canonical-format guard the workspace has, for the same reason: it is what
        # makes a structural diff of the fixture trustworthy.
        raw = open(_number_card("ipay_pending_over_an_hour")).read()
        self.assertEqual(frappe.as_json(json.loads(raw)), raw.rstrip("\n"))

    def test_the_card_carries_the_timestamp_that_lets_it_re_import(self):
        # The workspace has this guard because a fixture edit without a bump is silently
        # skipped. The expression lives in this file, so it needs the same floor: without
        # it, a corrected cutoff would sit in the repo looking shipped and never apply.
        card = self._card("ipay_pending_over_an_hour")
        self.assertGreaterEqual(card["modified"], PENDING_CARD_MODIFIED)

    # The identifiers the cutoff expression is allowed to reach. dashboard_utils.js:218
    # eval()s it in the browser, so a name that does not exist there throws at render time
    # and the card sticks on "Loading..." behind an error dialog. Everything here was
    # confirmed present in frappe 15: moment is window.moment (public/js/lib/moment.js:5)
    # and system_datetime is utils/datetime.js:232.
    CUTOFF_GLOBALS = {"moment.utc", "frappe.datetime.system_datetime"}

    def test_the_cutoff_expression_calls_only_names_that_exist_in_the_desk(self):
        # Guards the typo the structural tests cannot see: `system_date_time()` would pass
        # every other assertion in this class and ship a card that never renders.
        expression = self._age_filter()[3]
        called = set(re.findall(r"\b(?:[A-Za-z_$][\w$]*\.)+[A-Za-z_$][\w$]*(?=\()", expression))
        self.assertEqual(
            called - {"subtract", "format"}, self.CUTOFF_GLOBALS,
            "the expression reaches a name that was not checked against the desk bundle",
        )

    def test_the_cutoff_expression_really_resolves_to_one_hour_ago(self):
        """The only executable check on the only JavaScript in this change.

        Runs the real expression through the same moment-timezone build the desk bundles,
        with frappe.datetime.system_datetime reproduced from datetime.js:236-249. Skipped
        rather than faked where node or that build is absent, so a skip is visible.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available; cutoff expression not executed")
        moment_pkg = os.path.abspath(
            os.path.join(frappe.get_app_path("ipay"), "..", "..", "frappe",
                         "node_modules", "moment-timezone")
        )
        if not os.path.isdir(moment_pkg):
            self.skipTest(f"moment-timezone not found at {moment_pkg}; expression not executed")

        expression = self._age_filter()[3]
        script = """
            const moment = require(process.argv[1]);
            const FMT = "YYYY-MM-DD HH:mm:ss";
            const SYSTEM_TZ = "Africa/Nairobi";
            const frappe = { datetime: {
                system_datetime: () => moment.tz(SYSTEM_TZ).format(FMT),
            }};
            const cutoff = eval(process.argv[2]);
            const now = frappe.datetime.system_datetime();
            console.log(JSON.stringify({
                cutoff,
                minutes: moment(now, FMT).diff(moment(cutoff, FMT), "minutes"),
                shaped: /^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$/.test(cutoff),
            }));
        """
        def run(browser_tz):
            proc = subprocess.run(
                [node, "-e", script, moment_pkg, expression],
                capture_output=True, text=True, env={**os.environ, "TZ": browser_tz},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)

        # Africa/Nairobi has no DST; America/New_York does, and the cutoff must not move
        # with the viewer's own zone because `creation` is stored in system time.
        for browser_tz in ("Africa/Nairobi", "America/New_York", "Pacific/Chatham"):
            with self.subTest(browser_tz=browser_tz):
                result = run(browser_tz)
                self.assertTrue(result["shaped"], result["cutoff"])
                self.assertEqual(result["minutes"], 60, result)
