// Copyright (c) 2026, Gatura Njenga and contributors
// For license information, please see license.txt

frappe.listview_settings["iPay Cheque Collection"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		// Colour the accounts queue by where the cheque is: still out, collected and on its way,
		// physically in hand, or cancelled.
		return {
			Due: [__("Due"), "orange", "status,=,Due"],
			Collected: [__("Collected"), "blue", "status,=,Collected"],
			Received: [__("Physical copy received"), "green", "status,=,Received"],
			Cancelled: [__("Cancelled"), "gray", "status,=,Cancelled"],
		}[doc.status];
	},
};
