// Copyright (c) 2024, Gatura Njenga and contributors
// For license information, please see license.txt

frappe.ui.form.on('iPay Request', {
   refresh: function (frm) {
      // Check if the document is submitted
      const submitted = frm.doc.docstatus === 1;
      const status = frm.doc.status;

      // Make the status field read-only if payment is successful
      if (frm.doc.status === 'Success') {
         frm.set_df_property('status', 'read_only', 1);
      }

      // Add "Prompt iPay" button if submitted and status is not success
      if (submitted && status !== 'Success') {
         frm.add_custom_button(__('Prompt iPay'), () => {
            // Check if customer phone or email is missing
            if (!frm.doc.customer_phone || !frm.doc.customer_email) {
               frappe.msgprint({
                  title: __('Customer Phone OR Email Missing'),
                  message: __('The Phone and Email of the customer has to be provided in the Customer Doctype.'),
                  primary_action: {
                     label: __('Go to Customer'),
                     action() {
                        frappe.set_route('Form', 'Customer', frm.doc.customer);
                     },
                  },
                  secondary_action: {
                     label: __('Fetch Customer Details'),
                     action() {
                        // Fetch customer details via API call
                        frappe.call({
                           method: 'frappe.client.get',
                           args: {
                              doctype: 'Customer',
                              name: frm.doc.customer,
                           },
                           callback: function (r) {
                              if (r.message) {
                                 const customer = r.message;
                                 frm.set_value('customer_phone', customer.mobile_no || '');
                                 frm.set_value('customer_email', customer.email_id || '');
                                 frappe.msgprint(__('Customer details fetched successfully'));
                                 frm.save(); // Save updated values
                              } else {
                                 frappe.msgprint(__('No customer details found'));
                              }
                           },
                           error: function (err) {
                              frappe.msgprint(__('Failed to fetch customer details.'));
                              console.error('Fetch Customer Details Error:', err);
                           },
                        });
                     },
                  },
               });
            } else {
               // Prompt user for payment details before proceeding
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
                        reqd: 1,
                     },
                     {
                        label: 'Customer Email',
                        fieldname: 'customer_email',
                        fieldtype: 'Data',
                        default: frm.doc.customer_email,
                        reqd: 1,
                     },
                     {
                        label: 'Payment Method',
                        fieldname: 'payment_request_type',
                        fieldtype: 'Select',
                        options: 'Mpesa Express\nMpesa Paybill',
                        default: frm.doc.payment_request_type,
                     },
                  ],
                  (values) => {
                     // Confirm payment initiation
                     frappe.confirm(
                        'Are you sure you want to prompt iPay?',
                        () => {
                           // Extract last 8 digits of phone numbers for validation
                           const customerPhoneLast8 = frm.doc.customer_phone.slice(-8);
                           const promptedPhoneLast8 = values.customer_phone.slice(-8);

                           // If phone numbers differ, store prompted number separately
                           if (customerPhoneLast8 !== promptedPhoneLast8) {
                              frappe.db.set_value('iPay Request', frm.doc.name, 'prompted_number', values.customer_phone);
                           }

                           // If the prompted number matches the original, reset the prompted number field
                           if (frm.doc.prompted_number && customerPhoneLast8 === promptedPhoneLast8) {
                              frappe.db.set_value('iPay Request', frm.doc.name, 'prompted_number', null);
                           }

                           // Display success alert
                           frappe.show_alert({ message: 'iPay Prompted', indicator: 'green' }, 7);

                           // Initiate payment request via API
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
                                    //  handle response for Mpesa Paybill
                                    const message = r.message;
                                    if (Array.isArray(message) && message.length === 3) {
                                       const paybill = message[0];
                                       const account = message[1];
                                       const amount = message[2];
                                       frappe.msgprint({
                                          title: 'Payment Details',
                                          message: `<p><strong>Use the following details to make the payment</strong></p>
                                                    <br><br>
                                                    <p><strong>Paybill:</strong> ${paybill}</p>
                                                    <p><strong>Account Number:</strong> ${account}</p>
                                                    <p><strong>Amount:</strong> ${amount}</p>
                                                    <br><br>
                                                    <p style="color: red; font-weight: bold; text-align: center;">
                                                      ⚠️ Only Use MPESA, AIRTEL, OR EQUITEL. Only pay the exact amount.
                                                    </p>
                                                    <br><br>
                                                    <p style="font-style: italic; text-align: center;">Wait for a minute or two before confirming payment.</p>`,
                                          primary_action: {
                                             label: __('Confirm Payment'),
                                             action() {
                                                confirmPayment(frm);
                                             },
                                          },
                                          indicator: 'green',
                                       });
                                    } else {
                                       frappe.show_alert(
                                          {
                                             message: `iPay Prompted Successfully. The Payment Entry has been created`,
                                             indicator: 'blue',
                                          },
                                          15
                                       );
                                    }
                                 }
                              },
                              error: (err) => {
                                 frappe.show_alert(
                                    {
                                       message: 'Something went wrong: ' + err.message,
                                       indicator: 'red',
                                    },
                                    10
                                 );
                              },
                           });
                        },
                        () => {
                           frappe.msgprint('iPay Prompt Cancelled');
                        }
                     );
                  }
               );
            }
         })
            .addClass('btn-success')
            .removeClass('btn-default');
      }

      // Add "Verify Payment" button if payment is pending
      if (submitted && status && status !== 'Success') {
         frm.add_custom_button(__('Verify Payment'), () => {
            console.log('Verifying Payment');

            // Call API to verify payment status
            confirmPayment(frm);
         })
            .addClass('btn-primary')
            .removeClass('btn-default');
      }
   },
});

// function to call the verify payment API
function confirmPayment(frm) {
   // Collect payment verification parameters
   const docid = frm.doc.name;
   const user_id = frm.doc.customer;
   const phone = frm.doc.prompted_number || frm.doc.customer_phone;
   const amount = frm.doc.amount;
   const order = frm.doc.sales_invoice;
   const customer_email = frm.doc.customer_email;

   frappe.call({
      method: 'ipay.ipay.main.utils.confirm_payment.confirm_payment',
      args: { docid, user_id, phone, amount, order, customer_email },
      freeze: true,
      async: true,
      callback: function (r) {
         if (r.message) {
            const { status, message, data } = r.message;

            if (status === 'success') {
               // Extract transaction details
               const transactionCode = data?.transaction_code || 'N/A';
               const paymentMode = data?.payment_mode || 'N/A';
               const paidAt = data?.paid_at || 'N/A';

               // Display payment verification success message
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

               const inv = order;
               const response_data = data;

               frappe.call({
                  method: 'ipay.ipay.main.utils.make_payment_entry.make_payment_entry',
                  args: { user_id, customer_email, inv, response_data },
                  freeze: false,
                  async: true,

                  callback: function (r) {
                     const res = r.message;
                     if (res.status === 'duplicate') {
                        frappe.msgprint({
                           title: __('Duplicate Payment Entry'),
                           message: `A Payment Entry with the same transaction code already exists: 
                                    <a href="/app/payment-entry/${res.payment_entry}" target="_blank">${res.payment_entry}</a>`,
                           indicator: 'orange',
                        });
                     } else if (res.status === 'success') {
                        frappe.msgprint({
                           title: __('Payment Entry Created'),
                           message: `Payment Entry: <a href="/app/payment-entry/${res.payment_entry}" target="_blank">${res.payment_entry}</a>`,
                           indicator: 'green',
                        });
                     } else {
                        frappe.msgprint({
                           title: __('Payment Entry Error'),
                           message: __(res.message || 'An unknown error occurred while creating the payment entry.'),
                           indicator: 'red',
                        });
                     }
                  },
               });
            } else {
               // Handle verification failure
               frappe.msgprint({
                  title: __('Verification Failed'),
                  //  message: __(`Error: ${message}`),
                  message: `Error: Payment Not Found.`,
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
}
