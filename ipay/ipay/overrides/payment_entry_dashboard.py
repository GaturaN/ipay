def get_dashboard_data(data):
	"""Add the iPay Request to a Payment Entry's Connections, via custom_ipay_request. Extends
	(never replaces) the entry's existing dashboard — Frappe passes the current data in."""
	data.setdefault("internal_links", {})["iPay Request"] = "custom_ipay_request"
	data.setdefault("transactions", []).insert(0, {"label": "iPay", "items": ["iPay Request"]})
	return data
