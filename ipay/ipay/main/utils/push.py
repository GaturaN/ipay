"""Web Push (VAPID) for the iPay Collect PWA.

Subscriptions live in the `iPay Push Subscription` DocType (one row per browser install,
carrying the user's per-type on/off preferences). The frontend requests permission, subscribes
via the service worker, and POSTs the subscription here. `send_web_push` is the send path the
notification triggers (Phase 2) call.

VAPID keys live in site config (secrets, never committed):
  ipay_vapid_public_key   — base64url, also handed to the browser as applicationServerKey
  ipay_vapid_private_key  — base64url raw private key
  ipay_vapid_subject      — a mailto: or https: contact, e.g. "mailto:ops@bulkbox.cloud"
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

# Notification type -> the preference that gates it. A type not in this map (e.g. the test
# push) bypasses per-type filtering.
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


@frappe.whitelist()
def get_public_key():
	"""The VAPID public key the browser needs to subscribe (also exposed via boot)."""
	return _vapid()[0]


@frappe.whitelist(methods=["POST"])
def subscribe(subscription, user_agent=None):
	"""Store (or refresh) the caller's push subscription for this browser."""
	sub = json.loads(subscription) if isinstance(subscription, str) else subscription
	endpoint = (sub or {}).get("endpoint")
	keys = (sub or {}).get("keys") or {}
	p256dh, auth = keys.get("p256dh"), keys.get("auth")
	if not (endpoint and p256dh and auth):
		frappe.throw(_("Invalid push subscription."))

	user = frappe.session.user
	name = frappe.db.get_value(DOCTYPE, {"endpoint": endpoint}, "name")
	if name:
		# Same browser re-subscribing (keys rotate; the device may have switched account).
		doc = frappe.get_doc(DOCTYPE, name)
		doc.user = user
		doc.p256dh = p256dh
		doc.auth = auth
		if user_agent:
			doc.user_agent = user_agent
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"user": user,
				"endpoint": endpoint,
				"p256dh": p256dh,
				"auth": auth,
				"user_agent": user_agent,
			}
		).insert(ignore_permissions=True)
	return {"name": doc.name, "prefs": _prefs_of(doc)}


@frappe.whitelist(methods=["POST"])
def unsubscribe(endpoint):
	"""Remove the caller's subscription for this browser."""
	name = frappe.db.get_value(DOCTYPE, {"endpoint": endpoint, "user": frappe.session.user}, "name")
	if name:
		frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)
	return {"ok": True}


@frappe.whitelist()
def get_prefs(endpoint):
	"""The caller's saved preferences for this browser, or None if not subscribed."""
	name = frappe.db.get_value(DOCTYPE, {"endpoint": endpoint, "user": frappe.session.user}, "name")
	return _prefs_of(frappe.get_doc(DOCTYPE, name)) if name else None


@frappe.whitelist(methods=["POST"])
def set_prefs(endpoint, prefs):
	"""Update which notification types this browser's subscription receives."""
	prefs = json.loads(prefs) if isinstance(prefs, str) else prefs
	name = frappe.db.get_value(DOCTYPE, {"endpoint": endpoint, "user": frappe.session.user}, "name")
	if not name:
		frappe.throw(_("No subscription found for this device."))
	doc = frappe.get_doc(DOCTYPE, name)
	for field in PREF_FIELDS:
		if field in prefs:
			doc.set(field, 1 if prefs[field] else 0)
	doc.save(ignore_permissions=True)
	return _prefs_of(doc)


@frappe.whitelist(methods=["POST"])
def send_test():
	"""Send the caller a test notification (bypasses per-type preferences)."""
	sent = send_web_push(
		[frappe.session.user],
		title="iPay Collect",
		body="Notifications are on — you'll be alerted here.",
		notif_type=None,
		tag="ipay-test",
	)
	return {"sent": sent}


def send_web_push(users, title, body, notif_type=None, url="/collect", tag=None):
	"""Send a push to every enabled subscription of the given users.

	Honours each subscription's per-type preference (unless notif_type is None). Prunes
	subscriptions the push service reports as gone. Returns the number sent. Safe to call with
	no VAPID keys configured (returns 0) so it never breaks the flow that triggered it.
	"""
	recipients = [u for u in set(users or []) if u and u != "Guest"]
	if not recipients:
		return 0

	_pub, private_key, subject = _vapid()
	if not private_key:
		return 0

	filters = {"user": ["in", recipients]}
	pref_field = TYPE_TO_PREF.get(notif_type) if notif_type else None
	if pref_field:
		filters[pref_field] = 1

	subs = frappe.get_all(
		DOCTYPE, filters=filters, fields=["name", "endpoint", "p256dh", "auth"]
	)
	if not subs:
		return 0

	payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
	return sum(1 for s in subs if _send_one(s, payload, private_key, subject))


def _send_one(sub, payload, private_key, subject):
	try:
		from pywebpush import WebPushException, webpush
	except ImportError:
		from ipay.ipay.main.utils.ipay_logs import create_log_entry

		create_log_entry(
			"ERR",
			"pywebpush is not installed — web push skipped. Run: ./env/bin/pip install pywebpush",
		)
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
		status = getattr(getattr(exc, "response", None), "status_code", None)
		# 404/410 mean the browser dropped the subscription — stop trying it.
		if status in (404, 410):
			frappe.db.delete(DOCTYPE, {"name": sub["name"]})
		return False
	except Exception:
		frappe.log_error(frappe.get_traceback(), "iPay web push failed")
		return False
