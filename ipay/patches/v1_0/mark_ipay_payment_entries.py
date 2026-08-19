import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Stamp every iPay-collected Payment Entry so reports can tell them apart from the site's
	other M-Pesa entries (manual, bank reconciliation, other integrations all use mode MPESA)."""
	create_custom_fields(
		{
			"Payment Entry": [
				{
					"fieldname": "custom_ipay_request",
					"label": "iPay Request",
					"fieldtype": "Link",
					"options": "iPay Request",
					"insert_after": "mode_of_payment",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"description": "Set when this payment was collected through iPay.",
				}
			]
		},
		ignore_validate=True,
	)

	for req in frappe.get_all(
		"iPay Request", filters={"payment_entry": ["is", "set"]}, fields=["name", "payment_entry"]
	):
		if frappe.db.exists("Payment Entry", req.payment_entry):
			frappe.db.set_value(
				"Payment Entry", req.payment_entry, "custom_ipay_request", req.name, update_modified=False
			)
