"""Web Push (VAPID) for the Collect PWA.

Keys read from site config: ipay_vapid_public_key, ipay_vapid_private_key, ipay_vapid_subject.
"""

import json

import frappe
from frappe import _

DOCTYPE = "iPay Push Subscription"

PREF_FIELDS = (
	"notify_cheque_assigned",
	"notify_collection_success",
	"notify_collection_error",
)

TYPE_TO_PREF = {
	"cheque_assigned": "notify_cheque_assigned",
	"collection_success": "notify_collection_success",
	"collection_error": "notify_collection_error",
}


def _vapid():
	conf = frappe.conf
	return (
		conf.get("ipay_vapid_public_key"),
		conf.get("ipay_vapid_private_key"),
		conf.get("ipay_vapid_subject") or "mailto:admin@localhost",
	)


def _prefs_of(doc):
	return {field: int(doc.get(field) or 0) for field in PREF_FIELDS}


def _find(endpoint, user=None):
	filters = {"endpoint": endpoint}
	if user:
		filters["user"] = user
	return frappe.db.get_value(DOCTYPE, filters, "name")


@frappe.whitelist()
def get_public_key():
	return _vapid()[0]


@frappe.whitelist(methods=["POST"])
def subscribe(subscription, user_agent=None):
	sub = json.loads(subscription) if isinstance(subscription, str) else subscription
	endpoint = (sub or {}).get("endpoint")
	keys = (sub or {}).get("keys") or {}
	if not (endpoint and keys.get("p256dh") and keys.get("auth")):
		frappe.throw(_("Invalid push subscription."))

	name = _find(endpoint)
	doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
	doc.update(
		{
			"user": frappe.session.user,
			"endpoint": endpoint,
			"p256dh": keys["p256dh"],
			"auth": keys["auth"],
		}
	)
	if user_agent:
		doc.user_agent = user_agent
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "prefs": _prefs_of(doc)}


@frappe.whitelist(methods=["POST"])
def unsubscribe(endpoint):
	name = _find(endpoint, frappe.session.user)
	if name:
		frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)
	return {"ok": True}


@frappe.whitelist()
def get_prefs(endpoint):
	name = _find(endpoint, frappe.session.user)
	return _prefs_of(frappe.get_doc(DOCTYPE, name)) if name else None


@frappe.whitelist(methods=["POST"])
def set_prefs(endpoint, prefs):
	prefs = json.loads(prefs) if isinstance(prefs, str) else prefs
	name = _find(endpoint, frappe.session.user)
	if not name:
		frappe.throw(_("No subscription found for this device."))
	doc = frappe.get_doc(DOCTYPE, name)
	for field in PREF_FIELDS:
		if field in prefs:
			doc.set(field, 1 if prefs[field] else 0)
	doc.save(ignore_permissions=True)
	return _prefs_of(doc)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def collect_worker():
	"""Serve the built service worker with Service-Worker-Allowed: /collect, so it can be
	registered at /collect scope and control the app — which iOS requires to deliver push."""
	from werkzeug.wrappers import Response

	path = frappe.get_app_path("ipay", "public", "frontend", "sw.js")
	with open(path, encoding="utf-8") as handle:
		content = handle.read()
	response = Response(content, mimetype="text/javascript")
	response.headers["Service-Worker-Allowed"] = "/collect"
	response.headers["Cache-Control"] = "no-cache"
	frappe.local.response = response
	return response


@frappe.whitelist(methods=["POST"])
def send_test():
	sent = send_web_push(
		[frappe.session.user],
		title="iPay Collect",
		body="Notifications are on — you'll be alerted here.",
		tag="ipay-test",
	)
	return {"sent": sent}


def send_web_push(users, title, body, notif_type=None, url="/collect", tag=None):
	recipients = [u for u in set(users or []) if u and u != "Guest"]
	_public, private_key, subject = _vapid()
	if not (recipients and private_key):
		return 0

	filters = {"user": ["in", recipients]}
	pref_field = TYPE_TO_PREF.get(notif_type)
	if pref_field:
		filters[pref_field] = 1

	subs = frappe.get_all(DOCTYPE, filters=filters, fields=["name", "endpoint", "p256dh", "auth"])
	payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
	return sum(1 for sub in subs if _deliver(sub, payload, private_key, subject))


def _deliver(sub, payload, private_key, subject):
	try:
		from pywebpush import WebPushException, webpush
	except ImportError:
		return False

	try:
		webpush(
			subscription_info={
				"endpoint": sub["endpoint"],
				"keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
			},
			data=payload,
			vapid_private_key=private_key,
			vapid_claims={"sub": subject},
		)
		return True
	except WebPushException as exc:
		if getattr(getattr(exc, "response", None), "status_code", None) in (404, 410):
			frappe.db.delete(DOCTYPE, {"name": sub["name"]})
		return False
	except Exception:
		frappe.log_error(frappe.get_traceback(), "iPay web push failed")
		return False
