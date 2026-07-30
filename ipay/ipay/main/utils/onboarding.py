"""Per-user record of which first-run tours a user has seen — kept server-side so it survives a
cache clear, a new device or a PWA reinstall. Read into boot; written by mark_seen."""

import json

import frappe

DOCTYPE = "iPay Onboarding"


def seen_tours(user=None):
	user = user or frappe.session.user
	if not user or user == "Guest":
		return []
	raw = frappe.db.get_value(DOCTYPE, user, "seen_tours")
	try:
		return json.loads(raw) if raw else []
	except (ValueError, TypeError):
		return []


@frappe.whitelist(methods=["POST"])
def mark_seen(tour):
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
