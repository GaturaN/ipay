import { frappeRequest } from 'frappe-ui'

// The single place the SPA talks to the iPay backend. Every call rides the
// Frappe session cookie + CSRF token through frappeRequest, so it shares the
// logged-in desk session and the server-side operator/collector scoping.
function call(method, params, httpMethod = 'POST') {
  return frappeRequest({ url: `/api/method/${method}`, method: httpMethod, params })
}

const API = {
  collectionList: 'ipay.www.collect_payments.collection_list',
  collectionStats: 'ipay.www.collect_payments.collection_stats',
  promptMpesa: 'ipay.ipay.main.utils.ipay_redirect.prompt_mpesa',
  saveContact: 'ipay.ipay.main.utils.ipay_redirect.save_customer_contact',
  paymentState: 'ipay.ipay.main.utils.ipay_redirect.payment_state',
  startCheckout: 'ipay.ipay.main.utils.ipay_redirect.start_checkout',
}

export const fetchCollectionList = () => call(API.collectionList, {}, 'GET')

export const fetchCollectionStats = (driver) =>
  call(API.collectionStats, { driver: driver || '' }, 'GET')

export const promptMpesa = (invoice, phone) =>
  call(API.promptMpesa, { invoice, phone: phone || '' })

export const saveCustomerContact = (request, phone) =>
  call(API.saveContact, { request, phone })

export const paymentState = (request) => call(API.paymentState, { request }, 'GET')

// start_checkout is a GET that creates the request and 302-redirects to the
// hosted checkout, so it is used as a plain link target, not a fetch.
export const checkoutUrl = (invoice) =>
  `/api/method/${API.startCheckout}?invoice=${encodeURIComponent(invoice)}`
