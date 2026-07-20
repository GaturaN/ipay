"""The cheque pickup lifecycle: Due -> Collected -> Received.

Accounts often know a cheque is coming that the driver in the field does not. A pickup lets them
flag it, route it to a driver, and get it back with proof for banking. Every cheque a driver
records is tracked this way — scheduled or not — so the physical copy can be followed from the
field to the banking desk and none is ever lost in between.

Whether the money is banked is the Payment Entry's business (draft vs submitted), never a second
flag here — one source of truth for the ledger.
"""

import frappe
from frappe.utils import now_datetime

from ipay.ipay.main.utils.collector import my_driver_ids

DOCTYPE = "iPay Cheque Collection"
ACCOUNTS_ROLE = "Accounts Manager"
# The roles allowed to confirm a physical cheque has arrived.
RECEIPT_ROLES = {"Accounts Manager", "Accounts User", "iPay Manager", "System Manager"}
DUE_FIELDS = ["name", "customer", "customer_name", "expected_amount", "notes"]


def _oldest_open_due(customer):
	"""The oldest Due pickup for this customer — the one a collection completes, whoever brought
	the cheque in. Deliberately not scoped to the recorder's driver: operators and sales users map
	to no Driver at all, and the cheque is in the office however it arrived, so scoping here would
	leave the pickup open and send someone after a cheque already collected.
	None when accounts scheduled nothing (an ad-hoc collection)."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={"customer": customer, "status": "Due"},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	return rows[0] if rows else None


def has_open_pickup(customer):
	"""Has accounts flagged a cheque to collect from this customer? A grant to act on that
	customer, not to see them — keep it to the collect action, never a display scope."""
	return bool(frappe.db.exists(DOCTYPE, {"customer": customer, "status": "Due"}))


def advance_or_create_on_collect(customer, payment_entry, cheque_no, amount, image_url, collector):
	"""Track a just-recorded cheque. Completes the collector's oldest scheduled pickup for this
	customer, or opens a fresh Collected record when none was scheduled — so every collected
	cheque reaches the accounts receipt queue. Then hands it to accounts for banking.

	Runs after the money is already saved; the caller must swallow any error so a tracking
	failure can never undo a real cheque."""
	driver_ids = my_driver_ids(collector)
	proof = {
		"status": "Collected",
		"payment_entry": payment_entry,
		"cheque_no": cheque_no,
		"amount_collected": amount,
		"cheque_image": image_url,
		"collected_by": collector,
		"collected_on": now_datetime(),
	}
	name = _oldest_open_due(customer)
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.update(proof)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({
			"doctype": DOCTYPE,
			"customer": customer,
			# Ad-hoc collection has no scheduled driver: record the collector's own when they map
			# to one. Operators and sales users map to none, and a record that is already Collected
			# needs no driver — it is the receipt trail, not a dispatch.
			"driver": driver_ids[0] if driver_ids else None,
			**proof,
		})
		doc.insert(ignore_permissions=True)
	reassign_to_accounts(doc)
	return doc.name


def _banking_assignees():
	"""Who a collected cheque is handed to for banking: the configured user, else everyone
	enabled who holds the Accounts Manager role. Never the system user."""
	assignee = frappe.db.get_single_value("iPay Settings", "cheque_banking_assignee")
	if assignee:
		return [assignee] if assignee != "Administrator" else []
	holders = [
		u
		for u in frappe.get_all(
			"Has Role", filters={"role": ACCOUNTS_ROLE, "parenttype": "User"}, pluck="parent"
		)
		if u != "Administrator"
	]
	if not holders:
		return []
	return frappe.get_all(
		"User", filters={"name": ["in", holders], "enabled": 1}, pluck="name"
	)


def reassign_to_accounts(doc):
	"""Hand the pickup to the banking team via native assignment (their desk to-do), clearing
	any earlier assignment first so it lands only with accounts."""
	from frappe.desk.form import assign_to

	assign_to.close_all_assignments(DOCTYPE, doc.name, ignore_permissions=True)
	assignees = _banking_assignees()
	if not assignees:
		return
	assign_to.add(
		{
			"doctype": DOCTYPE,
			"name": doc.name,
			"assign_to": assignees,
			"description": f"Cheque collected from {doc.customer_name or doc.customer} "
			f"— receive the physical copy and bank it.",
		},
		ignore_permissions=True,
	)


@frappe.whitelist()
def mark_cheque_received(pickup):
	"""Accounts confirm the physical cheque is in hand. Stamps who/when and clears the to-do.
	The record is done here — banking (submitting the Payment Entry) stays the normal step."""
	roles = set(frappe.get_roles())
	if not (RECEIPT_ROLES & roles):
		frappe.throw("Only the accounts team can receive a cheque.", frappe.PermissionError)

	from frappe.desk.form import assign_to

	doc = frappe.get_doc(DOCTYPE, pickup)
	if doc.status != "Collected":
		frappe.throw("Only a collected cheque can be marked received.")
	doc.status = "Received"
	doc.received_by = frappe.session.user
	doc.received_on = now_datetime()
	doc.save(ignore_permissions=True)
	assign_to.close_all_assignments(DOCTYPE, doc.name, ignore_permissions=True)
	return doc.status


# --- Banner queries: which cheques are still to collect ---------------------------------------
# Each collect surface feeds its banner from the scope it already enforces — the driver sees only
# what is routed to them, operators see everything, sales sees its own book.

def open_dues_for_driver(user):
	"""Due pickups routed to this collector's driver(s) — the field app's banner."""
	drivers = my_driver_ids(user)
	if not drivers:
		return []
	return _due_rows({"driver": ["in", drivers]})


def all_open_dues():
	"""Every Due pickup — the internal (operator) banner."""
	return _due_rows({})


def open_dues_for_customers(customers):
	"""Due pickups for a set of customers — the sales banner, scoped to the member's book."""
	customers = list(customers or [])
	if not customers:
		return []
	return _due_rows({"customer": ["in", customers]})


def _due_rows(extra):
	filters = {"status": "Due"}
	filters.update(extra)
	return frappe.get_all(DOCTYPE, filters=filters, fields=DUE_FIELDS, order_by="creation asc")


def open_due_for_customer(customer, driver_ids=None):
	"""The single open Due for one customer (optionally within a driver scope), oldest first —
	what the customer-page banner shows, matching what a collection would complete. `driver_ids`
	of None means any driver (operator/sales view); an empty list means the collector is routed
	nothing, so nothing shows."""
	filters = {"status": "Due", "customer": customer}
	if driver_ids is not None:
		if not driver_ids:
			return None
		filters["driver"] = ["in", list(driver_ids)]
	rows = frappe.get_all(
		DOCTYPE, filters=filters, fields=DUE_FIELDS, order_by="creation asc", limit=1
	)
	return rows[0] if rows else None
