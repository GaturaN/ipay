// Passive alarm: flag iPay Requests that have no phone number, since M-Pesa
// prompts cannot be sent without one. Pure list-view config, no backend.
frappe.listview_settings['iPay Request'] = {
   add_fields: ['customer_phone', 'status'],
   get_indicator(doc) {
      if (!doc.customer_phone && doc.status !== 'Success') {
         return [__('Missing phone'), 'red', 'customer_phone,is,not set'];
      }
   },
};
