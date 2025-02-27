frappe.ui.form.on('Sales Invoice', {
   refresh: function (frm) {
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;
      const bal = frm.doc.outstanding_amount > 0;

      if (submitted && bal && status !== 'Paid') {
         frm.add_custom_button(__('iPay Request'), () => {
            // Get values from the sales invoice
            const customer = frm.doc.customer;
            const salesInvoice = frm.doc.name;

            // Check if an iPay Request already exists using get_list
            frappe.call({
               method: 'frappe.client.get_list',
               args: {
                  doctype: 'iPay Request',
                  filters: {
                     sales_invoice: salesInvoice,
                     docstatus: 1,
                  },
                  limit_page_length: 1, // Limit to one record for efficiency
                  fields: ['name'],
               },
               callback: function (response) {
                  if (response.message.length > 0) {
                     frappe.msgprint(__('An iPay Request for this Sales Invoice already exists'));
                     return;
                  }

                  // If no existing request, proceed to create a new one
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
                           frappe.show_alert({
                              message: __('iPay Request Created successfully'),
                              indicator: 'green',
                           });

                           // Confirm if user wants to be redirected
                           frappe.confirm(__('Do you want to be redirected to the newly created iPay Request?'), function () {
                              frappe.set_route('Form', 'iPay Request', r.message.name);
                           });
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
         args: {
            inv: frm.doc.name,
         },
         callback: function (r) {
            if (!r.message) {
               frappe.show_alert({
                  message: __('No response received from the server.'),
                  indicator: 'red',
               });
               return;
            }

            const { status, message } = r.message;

            if (status === 'success') {
               frappe.show_alert({
                  message: __(`iPay Request <a href="/app/ipay-request/${message}" target="_blank" style="font-weight:bold; color:white; text-decoration:underline;">${message}</a> created successfully.`),
                  indicator: 'green',
               });
            }
         },
      });
   },
});
