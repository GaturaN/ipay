"""Collection-event push notifications: resolve recipients, compose the message, and send on a
background queue via push.send_web_push."""

import json

import frappe

from ipay.ipay.main.utils import push


def _enqueue(users, title, body, notif_type, tag=None):
	recipients = [u for u in set(users or []) if u and u != "Guest"]
	if not recipients:
		return
	frappe.enqueue(
		push.send_web_push,
		queue="short",
		users=recipients,
		title=title,
		body=body,
		notif_type=notif_type,
		url="/collect",
		tag=tag,
	)


def _request_initiators(request_name):
	row = frappe.db.get_value("iPay Request", request_name, ["owner", "_assign"], as_dict=True) or {}
	users = {row.get("owner")} if row.get("owner") else set()
	if row.get("_assign"):
		try:
			users.update(json.loads(row["_assign"]))
		except (ValueError, TypeError):
			pass
	return users


def cheque_collection_assigned(doc, method=None):
	if doc.status != "Due" or not doc.driver:
		return
	if not (doc.has_value_changed("driver") or doc.has_value_changed("status")):
		return
	user = frappe.db.get_value("Driver", doc.driver, "user")
	if user:
		_enqueue(
			[user],
			title="Cheque collection assigned",
			body=f"Collect a cheque from {doc.customer_name or doc.customer}.",
			notif_type="cheque_assigned",
			tag=f"cheque-{doc.name}",
		)


def notify_collection_success(request_name, amount, payer=None):
	_enqueue(
		_request_initiators(request_name),
		title="Payment received",
		body=f"KES {amount} received{f' from {payer}' if payer else ''}.",
		notif_type="collection_success",
		tag=f"req-{request_name}",
	)


def notify_collection_error(request_name, reason=None):
	_enqueue(
		_request_initiators(request_name),
		title="Collection failed",
		body=reason or "The payment didn't go through.",
		notif_type="collection_error",
		tag=f"req-{request_name}",
	)


def _assignees(assign_json):
	if not assign_json:
		return set()
	try:
		return set(json.loads(assign_json))
	except (ValueError, TypeError):
		return set()


def _note_audience(customer, invoice):
	"""Everyone with a stake in the customer: the drivers who deliver to them, the sales people
	who own them, and anyone already involved (assigned a request, or who left a prior note).
	Uninvolved operators — who can see every customer — are deliberately excluded."""
	users = set()

	drivers = frappe.get_all(
		"Delivery Note",
		filters={"customer": customer, "docstatus": 1, "driver": ["is", "set"]},
		pluck="driver",
		distinct=True,
	)
	if drivers:
		users.update(
			frappe.get_all(
				"Driver", filters={"name": ["in", drivers], "user": ["is", "set"]}, pluck="user"
			)
		)

	sales_persons = set(
		frappe.get_all("Sales Team", filters={"parenttype": "Customer", "parent": customer}, pluck="sales_person")
	)
	sales_persons.update(
		frappe.get_all("Sales Team", filters={"parenttype": "Sales Invoice", "parent": invoice}, pluck="sales_person")
	)
	sales_persons.discard(None)
	if sales_persons:
		employees = frappe.get_all(
			"Sales Person", filters={"name": ["in", list(sales_persons)], "employee": ["is", "set"]}, pluck="employee"
		)
		if employees:
			users.update(
				frappe.get_all(
					"Employee", filters={"name": ["in", employees], "user_id": ["is", "set"]}, pluck="user_id"
				)
			)

	for row in frappe.get_all("iPay Request", filters={"customer": customer}, fields=["owner", "_assign"]):
		if row.owner:
			users.add(row.owner)
		users.update(_assignees(row._assign))

	invoices = frappe.get_all("Sales Invoice", filters={"customer": customer, "docstatus": 1}, pluck="name")
	if invoices:
		users.update(
			frappe.get_all(
				"Comment",
				filters={
					"reference_doctype": "Sales Invoice",
					"reference_name": ["in", invoices],
					"comment_type": "Comment",
				},
				pluck="owner",
			)
		)

	return users


def notify_note(invoice, author, note):
	"""A collector left a note on an invoice — alert the customer's audience, minus the author."""
	inv = frappe.db.get_value("Sales Invoice", invoice, ["customer", "customer_name"], as_dict=True)
	if not inv:
		return
	audience = _note_audience(inv.customer, invoice) - {author}
	snippet = (note or "").strip()
	if len(snippet) > 80:
		snippet = snippet[:79] + "…"
	_enqueue(
		audience,
		title=f"Note from {frappe.utils.get_fullname(author)}",
		body=f"{inv.customer_name or inv.customer}: {snippet}",
		notif_type="comment",
		tag=f"note-{inv.customer}",
	)
