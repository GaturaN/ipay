# Copyright (c) 2026, Gatura Njenga and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class iPayChequeCollection(Document):
	"""A cheque tracked from the moment accounts know it is due to the moment the physical copy
	is in their hands. The lifecycle (Due -> Collected -> Received) and the assignment hand-off
	live in ipay.ipay.main.utils.cheque_due; this controller only holds the record."""

	def validate(self):
		"""A scheduled pickup must be able to reach a collector. Only Due is checked: once the
		cheque is in, the record is a receipt trail and a system-created one has no driver at all.
		Frappe evaluates mandatory_depends_on client-side only, so the rule is enforced here."""
		if self.status != "Due":
			return
		if not self.driver:
			frappe.throw("Assign a driver — a pickup with no driver reaches no collect app.")
		if not frappe.db.get_value("Driver", self.driver, "user"):
			frappe.throw(
				f"Driver {self.driver} has no linked User, so this pickup would never appear "
				"in the collect app. Set that driver's User field first."
			)
