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

      // Payment links + hosted checkout exist only when "Use Hosted Checkout
      // Redirect" is on. With it off the org collects by direct M-Pesa prompt, so
      // the link field and the Copy/Regenerate buttons are hidden (the server
      // refuses these endpoints too — same single source of truth).
      if (submitted) {
         frappe.db.get_single_value('iPay Settings', 'enable_redirect').then((redirect) => {
            if (!redirect) {
               const field = frm.get_field('payment_link');
               if (field) {
                  field.$wrapper.html(
                     '<span class="text-muted">Payment links are off &mdash; "Use Hosted Checkout Redirect" is disabled in iPay Settings.</span>'
                  );
               }
               return;
            }

            // Render a persistent, clickable payment link on the form.
            render_payment_link(frm);

            // Copy a shareable payment link to send to the customer.
            if (status !== 'Success') {
               frm.add_custom_button(__('Copy Payment Link'), () => {
                  frappe.call({
                     method: 'ipay.ipay.main.utils.ipay_redirect.get_payment_link',
                     args: { request: frm.doc.name },
                     freeze: true,
                     callback: function (r) {
                        const res = r.message || {};
                        if (!res.url) { frappe.msgprint(__('Could not generate a payment link.')); return; }
                        if (navigator.clipboard) { navigator.clipboard.writeText(res.url); }
                        // Populate the persistent field immediately (frm.doc.pay_token
                        // is still stale on the client until the next reload).
                        set_payment_link_html(frm, res.url);
                        frappe.msgprint({
                           title: __('Payment Link (copied to clipboard)'),
                           message: `<div style="word-break:break-all"><a href="${res.url}" target="_blank">${res.url}</a></div>`,
                           indicator: 'blue',
                        });
                     },
                  });
               }, __('iPay Menu'));
            }

            // Regenerate the link (new token + expiry) if the old one lapsed or
            // was never used. Only while there is still a balance to collect.
            if (status !== 'Success' && status !== 'Overpaid') {
               frm.add_custom_button(__('Regenerate Payment Link'), () => {
                  frappe.confirm(
                     __('Issue a new payment link? The previous link will stop working.'),
                     () => {
                        frappe.call({
                           method: 'ipay.ipay.main.utils.ipay_redirect.regenerate_payment_link',
                           args: { request: frm.doc.name },
                           freeze: true,
                           callback: function (r) {
                              const res = r.message || {};
                              if (!res.url) { frappe.msgprint(__('Could not regenerate the link.')); return; }
                              if (navigator.clipboard) { navigator.clipboard.writeText(res.url); }
                              frappe.show_alert({ message: __('New link generated and copied.'), indicator: 'green' });
                              frm.reload_doc();
                           },
                        });
                     }
                  );
               }, __('iPay Menu'));
            }
         });
      }

      // Split a bundle back into individual requests (only before payment)
      if (submitted && status !== 'Success' && (frm.doc.invoices || []).length > 1) {
         frm.add_custom_button(__('Split into Individual Requests'), () => {
            frappe.confirm(
               __('Split this bundle into one request per invoice and cancel the bundle?'),
               () => {
                  frappe.call({
                     method: 'ipay.ipay.main.utils.ipay_redirect.split_bundle',
                     args: { request: frm.doc.name },
                     freeze: true,
                     callback: function (r) {
                        const res = r.message || {};
                        if (res.created) {
                           frappe.show_alert({ message: __(`Created ${res.created.length} request(s)`), indicator: 'green' });
                           frm.reload_doc();
                        }
                     },
                  });
               }
            );
         }, __('iPay Menu'));
      }

      // Add "Prompt iPay" button if submitted and status is not success
      if (submitted && status !== 'Success') {
         frm.add_custom_button(__('Prompt iPay'), () => {
            // Block only on a missing PHONE (email is optional for iPay). Offer
            // to enter a number now and save it to the Customer for next time.
            if (!frm.doc.customer_phone) {
               frappe.msgprint({
                  title: __('Customer Phone Missing'),
                  message: __('This customer has no phone number on file. Enter one to prompt for payment — it is saved to the Customer so future requests are pre-filled.'),
                  primary_action: {
                     label: __('Enter & Save Number'),
                     action() {
                        frappe.prompt(
                           [
                              { label: 'Customer Phone', fieldname: 'phone', fieldtype: 'Data', reqd: 1 },
                              { label: 'Customer Email (optional)', fieldname: 'email', fieldtype: 'Data' },
                           ],
                           (v) => {
                              frappe.call({
                                 method: 'ipay.ipay.main.utils.ipay_redirect.save_customer_contact',
                                 args: { request: frm.doc.name, phone: v.phone, email: v.email },
                                 callback: () => {
                                    frappe.hide_msgprint();
                                    frappe.show_alert({ message: __('Saved. Click "Prompt iPay" again to continue.'), indicator: 'green' });
                                    frm.reload_doc();
                                 },
                              });
                           },
                           __('Enter Customer Contact'), __('Save')
                        );
                     },
                  },
                  secondary_action: {
                     label: __('Go to Customer'),
                     action() {
                        frappe.set_route('Form', 'Customer', frm.doc.customer);
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
                        reqd: 0,
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

                           // Persist any newly-entered contact to the Customer
                           // (the server writes only blank fields), so future
                           // requests are pre-filled and never error.
                           frappe.call({
                              method: 'ipay.ipay.main.utils.ipay_redirect.save_customer_contact',
                              args: { request: frm.doc.name, phone: values.customer_phone, email: values.customer_email },
                           });

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
                                       // Express STK is processed on a background
                                       // worker; the result appears on the request
                                       // shortly (status / Payment Entry).
                                       frappe.show_alert(
                                          {
                                             message: `M-Pesa prompt sent. It will confirm in the background — reload or use "Verify Payment" to see the result.`,
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
               // confirm_payment now records the Payment Entry server-side and
               // returns it, so just surface the result here.
               // Escape values that originate from iPay's API response before
               // embedding them in msgprint HTML (defence against a malicious /
               // MITM'd response injecting markup).
               const esc = frappe.utils.escape_html;
               const transactionCode = esc(data?.transaction_code || 'N/A');
               const paymentMode = esc(data?.payment_mode || 'N/A');
               const paidAt = esc(data?.paid_at || 'N/A');
               const peName = r.message.payment_entry || '';
               const paymentEntry = esc(peName);
               const paymentEntryUrl = encodeURIComponent(peName);
               const requestStatus = esc(r.message.request_status || 'Recorded');
               const dupNote = r.message.is_duplicate
                  ? '<p><em>This payment was already recorded.</em></p>'
                  : '';

               frappe.msgprint({
                  title: __('Payment Verified'),
                  message: `
                    <p><strong>Status:</strong> ${requestStatus}</p>
                    <p><strong>Transaction Code:</strong> ${transactionCode}</p>
                    <p><strong>Payment Mode:</strong> ${paymentMode}</p>
                    <p><strong>Paid At:</strong> ${paidAt}</p>
                    ${dupNote}
                    <p><strong>Payment Entry:</strong> <a href="/app/payment-entry/${paymentEntryUrl}" target="_blank">${paymentEntry}</a></p>
                    `,
                  indicator: 'green',
               });
               frm.reload_doc();
            } else {
               // Surface the real reason from the server (payment not found, or
               // the payment was found but could not be recorded) so the
               // operator can act on a received-but-unrecorded payment.
               frappe.msgprint({
                  title: __('Verification Failed'),
                  message: __(message || 'Payment not found.'),
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

// Render the payment link into the read-only "Payment Link" HTML field so the
// operator can click it directly from the form (not only via the popup).
function render_payment_link(frm) {
   const field = frm.get_field('payment_link');
   if (!field) { return; }
   if (frm.doc.status === 'Success') {
      field.$wrapper.html('<span class="text-muted">This request has been paid.</span>');
   } else if (frm.doc.pay_token) {
      const url = `${window.location.origin}/pay?token=${encodeURIComponent(frm.doc.pay_token)}`;
      set_payment_link_html(frm, url, frm.doc.pay_token_expiry);
   } else {
      field.$wrapper.html('<span class="text-muted">Use "Copy Payment Link" to generate the link.</span>');
   }
}

function set_payment_link_html(frm, url, expiry) {
   const field = frm.get_field('payment_link');
   if (!field) { return; }
   const safe = frappe.utils.escape_html(url);
   let note = '';
   if (expiry) {
      const expired = frappe.datetime.now_datetime() > expiry;
      note = expired
         ? '<br><span style="color:#c0392b">Link expired &mdash; click "Regenerate Payment Link".</span>'
         : `<br><span class="text-muted">Valid until ${frappe.datetime.str_to_user(expiry)}</span>`;
   }
   field.$wrapper.html(
      `<a href="${safe}" target="_blank" rel="noopener" style="word-break:break-all">${safe}</a>${note}`
   );
}
