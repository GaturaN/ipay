"""Per-user onboarding state — which first-run tours a user has seen, kept server-side so it
survives a cache clear, a new browser, a different device, or a PWA reinstall. Exposed to the
SPA via boot (ipay.www.collect.get_boot) and updated by mark_seen when a tour ends."""

import json

import frappe

DOCTYPE = "iPay Onboarding"


def seen_tours(user=None):
	"""The list of tour keys this user has completed or skipped."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return []
	raw = frappe.db.get_value(DOCTYPE, user, "seen_tours")
	try:
		return json.loads(raw) if raw else []
	except (ValueError, TypeError):
		return []


@frappe.whitelist()
def get_seen():
	return seen_tours()


@frappe.whitelist(methods=["POST"])
def mark_seen(tour):
	"""Record that the caller has seen a first-run tour. Idempotent."""
	user = frappe.session.user
	if not tour or user == "Guest":
		return {"seen": []}
	current = set(seen_tours(user))
	if tour in current:
		return {"seen": sorted(current)}
	current.add(tour)
	doc = frappe.get_doc(DOCTYPE, user) if frappe.db.exists(DOCTYPE, user) else frappe.new_doc(DOCTYPE)
	doc.user = user
	doc.seen_tours = json.dumps(sorted(current))
	doc.save(ignore_permissions=True)
	return {"seen": sorted(current)}
