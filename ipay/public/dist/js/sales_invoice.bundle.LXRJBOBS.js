(() => {
  // ../ipay/ipay/public/js/sales_invoice.js
  frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;
      const bal = frm.doc.outstanding_amount > 0;
      if (submitted && bal && status !== "Paid") {
        frm.add_custom_button(__("iPay Request"), () => {
          const customer = frm.doc.customer;
          const salesInvoice = frm.doc.name;
          frappe.call({
            method: "frappe.client.insert",
            args: {
              doc: {
                doctype: "iPay Request",
                customer,
                sales_invoice: salesInvoice,
                docstatus: 1
              }
            },
            freeze: true,
            async: true,
            callback: function(r) {
              if (!r.exc) {
                frappe.show_alert({
                  message: __("iPay Request Created successfully"),
                  indicator: "green"
                }, 5);
                frappe.confirm(__("Do you want to be redirected to the newly created iPay Request?"), function() {
                  frappe.set_route("Form", "iPay Request", r.message.name);
                }, function() {
                  console.log("User chose not to be redirected.");
                });
              } else {
                frappe.msgprint(__("Failed to create iPay Request"));
              }
            }
          });
        }).addClass("btn-warning").removeClass("btn-default");
      }
    }
  });
})();
//# sourceMappingURL=sales_invoice.bundle.LXRJBOBS.js.map
