(() => {
  // ../ipay/ipay/public/js/sales_invoice.js
  frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;
      const bal = frm.doc.outstanding_amount > 0;
      if (submitted && bal && status !== "Paid") {
        frm.add_custom_button(__("iPay Request"), () => {
          console.log("Button Working");
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
                frappe.msgprint(__("iPay Request Created successfully"));
                frappe.set_route("Form", "iPay Request", r.message.name);
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
//# sourceMappingURL=sales_invoice.bundle.N3IOXKKM.js.map
