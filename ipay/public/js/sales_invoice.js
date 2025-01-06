frappe.ui.form.on("Sales Invoice", {
   refresh(frm) {
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;
      const bal = frm.doc.outstanding_amount > 0;

      if (submitted && bal && status !== "Paid") {
         frm.add_custom_button(__("iPay Request"), () => {
            // console.log("Button Working");
            //get values from the sales invoice and create an ipay request
            const customer = frm.doc.customer;
            const salesInvoice = frm.doc.name;

            // call the frappe.client.insert to create an ipay request
            frappe.call({
               method: "frappe.client.insert",
               args: {
                  doc: {
                     doctype: "iPay Request",
                     customer: customer,
                     sales_invoice: salesInvoice,
                     docstatus: 1,
                  },
               },
               freeze: true,
               async: true,
               callback: function (r) {
                  if (!r.exc) {
                     //  frappe.msgprint(__("iPay Request Created successfully"));
                     // show notification
                     frappe.show_alert(
                        {
                           message: __("iPay Request Created successfully"),
                           indicator: "green",
                        },
                        5
                     );
                     //  FEATURE: confirm if user want to be redirected
                     frappe.confirm(
                        __("Do you want to be redirected to the newly created iPay Request?"),
                        function () {
                           // Action for "Yes"
                           frappe.set_route("Form", "iPay Request", r.message.name);
                        },
                        function () {
                           // Action for "No"
                           console.log("User chose not to be redirected.");
                        }
                     );
                  } else {
                     frappe.msgprint(__("Failed to create iPay Request"));
                  }
               },
            });
         })
            .addClass("btn-warning")
            .removeClass("btn-default");
      }
   },
});

// TODO: Make cration of ipay request automatic for COD Sales Invoices.
