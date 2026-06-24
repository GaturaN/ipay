# Copyright (c) 2024, Gatura Njenga and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from frappe.website.website_generator import WebsiteGenerator

from ipay.ipay.main.utils.prepaid import is_sales_invoice_prepaid


class iPayRequest(WebsiteGenerator):
	def before_validate(self):
		# Prepaid invoices are settled automatically (wave_sync creates their
		# Payment Entry on submit), so they never need an iPay request. This is
		# the one chokepoint every creation path funnels through. Only check on
		# create — the classification never changes and later saves shouldn't pay
		# the query cost. Drop prepaid invoices from a bundle; block a single one.
		if self.is_new():
			if self.invoices:
				self.set("invoices", [
					row for row in self.invoices
					if not is_sales_invoice_prepaid(row.sales_invoice)
				])
				if not self.invoices:
					frappe.throw(
						"All selected invoices are prepaid and settle automatically; "
						"no iPay payment request is needed."
					)
			elif self.sales_invoice and is_sales_invoice_prepaid(self.sales_invoice):
				frappe.throw(
					"This invoice is prepaid and settles automatically; "
					"no iPay payment request is needed."
				)

		# For a bundle (the `invoices` table), default the primary Sales Invoice
		# from a remaining row so the mandatory sales_invoice field is satisfied
		# from the table alone (e.g. when created from the desk).
		if self.invoices:
			names = {row.sales_invoice for row in self.invoices}
			if not self.sales_invoice or self.sales_invoice not in names:
				self.sales_invoice = self.invoices[0].sales_invoice

	def validate(self):
		# A single-invoice request keeps the fetched amount; a bundle's amount is
		# the sum of its invoices' live outstanding, and all invoices must belong
		# to this request's customer and one company.
		if not self.invoices:
			return

		total = 0.0
		companies = set()
		for row in self.invoices:
			si = frappe.db.get_value(
				"Sales Invoice",
				row.sales_invoice,
				["customer", "company", "outstanding_amount"],
				as_dict=True,
			)
			if not si:
				continue
			if self.customer and si.customer != self.customer:
				frappe.throw(f"Invoice {row.sales_invoice} does not belong to {self.customer}.")
			companies.add(si.company)
			row.outstanding_amount = flt(si.outstanding_amount)
			total += flt(si.outstanding_amount)

		if len(companies) > 1:
			frappe.throw("All invoices in a bundle must belong to the same company.")

		self.amount = f"{total:.2f}"
