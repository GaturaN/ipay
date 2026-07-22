// Copyright (c) 2026, Gatura Njenga and contributors
// For license information, please see license.txt

frappe.ui.form.on("iPay Cheque Collection", {
	refresh(frm) {
		// The one accounts action: confirm the physical cheque has arrived. Banking (submitting
		// the Payment Entry) stays their normal step and is not duplicated here.
		if (frm.doc.status === "Collected") {
			frm
				.add_custom_button(__("Mark Physical Copy Received"), () => {
					frappe.confirm(
						__("Confirm the physical cheque from {0} is in hand?", [
							frm.doc.customer_name || frm.doc.customer,
						]),
						() => {
							frappe
								.call({
									method: "ipay.ipay.main.utils.cheque_due.mark_cheque_received",
									args: { pickup: frm.doc.name },
									freeze: true,
									freeze_message: __("Recording receipt…"),
								})
								.then(() => frm.reload_doc());
						},
					);
				})
				.addClass("btn-primary");
		}

		show_banked_state(frm);
	},
});

function show_banked_state(frm) {
	// Whether the money is banked is the Payment Entry's business, never a stored flag — read it
	// live and show it, so accounts see at a glance what still needs depositing.
	if (!frm.doc.payment_entry) return;
	frappe.db.get_value("Payment Entry", frm.doc.payment_entry, "docstatus").then((r) => {
		const banked = r && r.message && cint(r.message.docstatus) === 1;
		frm.dashboard.add_indicator(
			banked ? __("Banked") : __("Awaiting banking"),
			banked ? "green" : "orange",
		);
	});
}
