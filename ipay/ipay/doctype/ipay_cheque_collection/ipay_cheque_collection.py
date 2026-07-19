# Copyright (c) 2026, Gatura Njenga and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class iPayChequeCollection(Document):
	"""A cheque tracked from the moment accounts know it is due to the moment the physical copy
	is in their hands. The lifecycle (Due -> Collected -> Received) and the assignment hand-off
	live in ipay.ipay.main.utils.cheque_due; this controller only holds the record."""

	pass
