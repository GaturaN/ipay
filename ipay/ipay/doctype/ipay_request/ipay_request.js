// Copyright (c) 2024, Gatura Njenga and contributors
// For license information, please see license.txt

frappe.ui.form.on('iPay Request', {
   refresh: function (frm) {
      // add custom button if status is empty
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;

      // check if the status is set to "Success" and set the field to read-only
      if (frm.doc.status === 'Success') {
         frm.set_df_property('status', 'read_only', 1);
      }

      if (submitted && status !== 'Success') {
         frm.add_custom_button(__('Prompt iPay'), () => {
            // console.log("Payment Prompted");
            // prompt and confirm customer details
            frappe.prompt(
               [
                  {
                     label: 'Amount',
                     fieldname: 'amount',
                     fieldtype: 'Data',
                     default: frm.doc.amount,
                     read_only: 1,
                  },
                  {
                     label: 'Invoice Number',
                     fieldname: 'invoice_number',
                     fieldtype: 'Data',
                     default: frm.doc.sales_invoice,
                     read_only: 1,
                  },
                  {
                     label: 'User ID',
                     fieldname: 'user_id',
                     fieldtype: 'Data',
                     default: frm.doc.customer,
                     read_only: 1,
                  },
                  {
                     label: 'Customer Phone',
                     fieldname: 'customer_phone',
                     fieldtype: 'Data',
                     default: frm.doc.customer_phone,
                     read_only: 0,
                  },
                  {
                     label: 'Customer Email',
                     fieldname: 'customer_email',
                     fieldtype: 'Data',
                     default: frm.doc.customer_email,
                     read_only: 0,
                  },
                  {
                     label: 'Payment Method',
                     fieldname: 'payment_request_type',
                     fieldtype: 'Select',
                     options: 'Mpesa Express\nMpesa Paybill',
                     default: frm.doc.payment_request_type,
                     read_only: 0,
                  },
               ],
               (values) => {
                  frappe.confirm(
                     'Are you sure you want to prompt iPay?',
                     () => {
                        // Extract the last 8 digits of the phone numbers
                        const customerPhoneLast8 = frm.doc.customer_phone.slice(-8);
                        const promptedPhoneLast8 = values.customer_phone.slice(-8);

                        // compare the phone numbers, and if different save the prompted number in a different field
                        if (customerPhoneLast8 !== promptedPhoneLast8) {
                           frappe.db.set_value('iPay Request', frm.doc.name, 'prompted_number', values.customer_phone);
                        }

                        // if prompted again and prompted number is same as customer number, prompted number blank
                        if (frm.doc.prompted_number && customerPhoneLast8 === promptedPhoneLast8) {
                           frappe.db.set_value('iPay Request', frm.doc.name, 'prompted_number', null);
                        }

                        // show UI alert
                        frappe.show_alert(
                           {
                              message: 'iPay Prompted',
                              indicator: 'green',
                           },
                           7
                        );

                        console.log('values from prompt', values);

                        // call the lipana_mpesa function
                        frappe.call({
                           method: 'ipay.ipay.main.main.lipana_mpesa',
                           args: {
                              docid: frm.doc.name,
                              oid: values.invoice_number,
                              amount: values.amount,
                              customer_email: values.customer_email,
                              phone: values.customer_phone,
                              user_id: values.user_id,
                              payment_request_type: values.payment_request_type,
                           },
                           freeze: false,
                           async: true,
                           callback: function (r) {
                              if (r.message) {
                                 //  access the response from the server
                                 const data = r.message;
                                 // display the transaction code in the success message
                                 frappe.show_alert(
                                    {
                                       message: `iPay Prompted Successfully. The Payment Entry has been created`,
                                       indicator: 'blue',
                                    },
                                    15
                                 );
                              }
                           },
                           error: (err) => {
                              frappe.msgprint({
                                 title: 'Error',
                                 message: 'Something went wrong: ' + err.message,
                                 indicator: 'red',
                              });
                           },
                        });
                     },
                     () => {
                        frappe.msgprint('iPay Prompt Cancelled');
                     }
                  );
               }
            );
         })
            .addClass('btn-success')
            .removeClass('btn-default');
      }
      if (submitted && status && status !== 'Success') {
         frm.add_custom_button(__('Verify Payment'), () => {
            console.log('Verifying Payment');

            // get the parameters from the form
            const docid = frm.doc.name;
            const user_id = frm.doc.customer;
            const phone = frm.doc.prompted_number || frm.doc.customer_phone;
            const amount = frm.doc.amount;
            const order = frm.doc.sales_invoice;
            const customer_email = frm.doc.customer_email;

            // call the verify_payment function
            frappe.call({
               method: 'ipay.ipay.main.utils.confirm_payment.confirm_payment',
               args: {
                  docid: docid,
                  user_id: user_id,
                  phone: phone,
                  amount: amount,
                  order: order,
                  customer_email: customer_email,
               },
               freeze: true,
               async: true,
               callback: function (r) {
                  if (r.message) {
                     const { status, message, data } = r.message;

                     if (status === 'success') {
                        //  access the response from the server
                        const transactionCode = data?.transaction_code || 'N/A';
                        const paymentMode = data?.payment_mode || 'N/A';
                        const paidAt = data?.paid_at || 'N/A';

                        frappe.msgprint({
                           title: __('Payment Verified'),
                           message: `
                           <p><strong>Status:</strong> The payment has been verified successfully.</p>
                           <p><strong>Transaction Code:</strong> ${transactionCode}</p>
                           <p><strong>Payment Mode:</strong> ${paymentMode}</p>
                           <p><strong>Paid At:</strong> ${paidAt}</p>
                        `,
                           indicator: 'green',
                        });
                     } else if (status === 'error') {
                        frappe.msgprint({
                           title: __('Verification Failed'),
                           message: __(`Error: ${message}`),
                           indicator: 'red',
                        });
                     }
                  } else {
                     frappe.msgprint({
                        title: __('Verification Error'),
                        message: __('No response from the server. Please try again.'),
                        indicator: 'orange',
                     });
                  }
               },
               error: function (err) {
                  frappe.msgprint({
                     title: __('Verification Error'),
                     message: __('An error occurred while verifying the payment. Please check the logs.'),
                     indicator: 'red',
                  });
                  console.error('Verification Error:', err);
               },
            });
         })
            .addClass('btn-primary')
            .removeClass('btn-default');
      }
   },
});
