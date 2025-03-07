frappe.ui.form.on('Sales Invoice', {
   refresh: function (frm) {
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;
      const bal = frm.doc.outstanding_amount > 0;

      if (submitted && bal && status !== 'Paid') {
         frm.add_custom_button(__('iPay Request'), () => {
            const customer = frm.doc.customer;
            const salesInvoice = frm.doc.name;

            // Check if an iPay Request already exists
            frappe.call({
               method: 'frappe.client.get_list',
               args: {
                  doctype: 'iPay Request',
                  filters: { sales_invoice: salesInvoice, docstatus: 1 },
                  fields: ['name'],
                  limit_page_length: 1,
               },
               callback: function (response) {
                  if (response.message.length > 0) {
                     const ipay_request_name = response.message[0].name;
                     const ipay_request_url = `/app/ipay-request/${ipay_request_name}`;

                     frappe.msgprint({
                        title: __('iPay Request Exists'),
                        message: __(
                           `An iPay Request for this Sales Invoice already exists. 
                          <a href="${ipay_request_url}" target="_blank" style="font-weight:bold; color:#007bff;">Click here to view</a>`
                        ),
                        indicator: 'green',
                     });

                     return;
                  }

                  // If no existing request, create a new iPay Request
                  frappe.call({
                     method: 'frappe.client.insert',
                     args: {
                        doc: {
                           doctype: 'iPay Request',
                           customer: customer,
                           sales_invoice: salesInvoice,
                           docstatus: 1,
                        },
                     },
                     freeze: true,
                     callback: function (r) {
                        if (!r.exc) {
                           const ipay_request_name = r.message.name;

                           frappe.show_alert({
                              message: __('iPay Request Created successfully'),
                              indicator: 'green',
                           });

                           frappe.confirm(__('Do you want to be redirected to the newly created iPay Request?'), function () {
                              frappe.set_route('Form', 'iPay Request', ipay_request_name);
                           });

                           // Store iPay Request name in frm for later use
                           frm.doc.ipay_request = ipay_request_name;
                        } else {
                           frappe.msgprint(__('Failed to create iPay Request'));
                        }
                     },
                  });
               },
            });
         })
            .addClass('btn-warning')
            .removeClass('btn-default');
      }
   },

   on_submit: function (frm) {
      frappe.call({
         method: 'ipay.ipay.main.utils.cod_create_request.create_request',
         args: { inv: frm.doc.name },
         callback: function (r) {
            if (!r.message) {
               frappe.show_alert({
                  message: __('No response received from the server.'),
                  indicator: 'red',
               });
               return;
            }

            const { status, message: ipay_request_name } = r.message;

            if (status === 'success') {
               frappe.show_alert({
                  message: __(`iPay Request <a href="/app/ipay-request/${ipay_request_name}" target="_blank" style="font-weight:bold; color:white; text-decoration:underline;">${ipay_request_name}</a> created successfully.`),
                  indicator: 'green',
               });

               frappe.call({
                  method: 'ipay.ipay.main.utils.driver.update_driver',
                  args: { request_name: ipay_request_name },
                  callback: function (r) {
                     if (r.message && r.message.status === 'success') {
                        frappe.show_alert({
                           message: __('Driver updated: ' + r.message.driver_name),
                           indicator: 'blue',
                        });
                     }
                  },
               });
            }
         },
      });
   },
});
