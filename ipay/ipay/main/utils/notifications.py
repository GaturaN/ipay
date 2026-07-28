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
