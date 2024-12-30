// Copyright (c) 2024, Gatura Njenga and contributors
// For license information, please see license.txt

frappe.ui.form.on("iPay Request", {
   refresh: function (frm) {
      // add custom button if status is empty
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status === "";

      if (submitted && status) {
         frm.add_custom_button(__("Prompt iPay"), () => {
            // console.log("Payment Prompted");
            // prompt and confirm customer details
            frappe.prompt(
               [
                  {
                     label: "Amount",
                     fieldname: "amount",
                     fieldtype: "Data",
                     default: frm.doc.amount,
                     read_only: 1,
                  },
                  {
                     label: "Invoice Number",
                     fieldname: "invoice_number",
                     fieldtype: "Data",
                     default: frm.doc.sales_invoice,
                     read_only: 1,
                  },
                  {
                     label: "User ID",
                     fieldname: "user_id",
                     fieldtype: "Data",
                     default: frm.doc.customer_phone,
                     read_only: 1,
                  },
                  {
                     label: "Customer Phone",
                     fieldname: "customer_phone",
                     fieldtype: "Data",
                     default: frm.doc.customer_phone,
                     read_only: 0,
                  },
                  {
                     label: "Customer Email",
                     fieldname: "customer_email",
                     fieldtype: "Data",
                     default: frm.doc.customer_email,
                     read_only: 0,
                  },
               ],
               (values) => {
                  frappe.confirm(
                     "Are you sure you want to prompt iPay?",
                     () => {
                        // logic to handle confirmation
                        frappe.show_alert(
                           {
                              message: "iPay Prompted",
                              indicator: "green",
                           },
                           7
                        );

                        console.log("values from prompt", values);

                        // call the lipana_mpesa function
                        frappe.call({
                           method: "ipay.ipay.main.main.lipana_mpesa",
                           args: {
                              oid: values.invoice_number,
                              amount: values.amount,
                              customer_email: values.customer_email,
                              phone: values.customer_phone,
                              user_id: values.user_id,
                           },
                           freeze: false,
                           async: true,
                           callback: function (r) {
                              if (r.message) {
                                 frappe.msgprint({
                                    title: "Success",
                                    message: r.message,
                                    indicator: "green",
                                 });
                              }
                           },
                           error: (err) => {
                              frappe.msgprint({
                                 title: "Error",
                                 message: "Something went wrong: " + err.message,
                                 indicator: "red",
                              });
                           },
                        });
                     },
                     () => {
                        frappe.msgprint("iPay Prompt Cancelled");
                     }
                  );
               }
            );
         })
            .addClass("btn-success")
            .removeClass("btn-default");
      }
   },
});
