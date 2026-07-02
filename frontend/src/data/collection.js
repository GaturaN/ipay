import { frappeRequest } from 'frappe-ui'

// The single place the SPA talks to the iPay backend. Every call rides the
// Frappe session cookie + CSRF token through frappeRequest, so it shares the
// logged-in desk session and the server-side operator/collector scoping.
function call(method, params, httpMethod = 'POST') {
  return frappeRequest({ url: `/api/method/${method}`, method: httpMethod, params })
}

const API = {
  collectionCustomers: 'ipay.www.collect_payments.collection_customers',
  customerCollection: 'ipay.www.collect_payments.customer_collection',
  internalCustomers: 'ipay.www.collect_payments.internal_customers',
  internalCustomerInvoices: 'ipay.www.collect_payments.internal_customer_invoices',
  collectionStats: 'ipay.www.collect_payments.collection_stats',
  promptMpesa: 'ipay.ipay.main.utils.ipay_redirect.prompt_mpesa',
  promptRequest: 'ipay.ipay.main.utils.ipay_redirect.prompt_request_mpesa',
  saveContact: 'ipay.ipay.main.utils.ipay_redirect.save_customer_contact',
  paymentState: 'ipay.ipay.main.utils.ipay_redirect.payment_state',
  createBundle: 'ipay.ipay.main.utils.ipay_redirect.create_bundle',
  requestDetail: 'ipay.ipay.main.utils.ipay_redirect.request_detail',
  paymentLink: 'ipay.ipay.main.utils.ipay_redirect.get_payment_link',
  regenerateLink: 'ipay.ipay.main.utils.ipay_redirect.regenerate_payment_link',
  discardBundle: 'ipay.ipay.main.utils.ipay_redirect.discard_bundle',
  startCheckout: 'ipay.ipay.main.utils.ipay_redirect.start_checkout',
}

// Top-level list: customers with an outstanding collect-on-delivery balance,
// optionally scoped to one driver's deliveries.
export const fetchCollectionCustomers = (driver) =>
  call(API.collectionCustomers, { driver: driver || '' }, 'GET')

// Drill-down: one customer's outstanding invoices, optionally driver-scoped.
export const fetchCustomerCollection = (customer, driver) =>
  call(API.customerCollection, { customer, driver: driver || '' }, 'GET')

export const fetchCollectionStats = (driver, allTerms) =>
  call(API.collectionStats, { driver: driver || '', all_terms: allTerms ? 1 : 0 }, 'GET')

// Internal (operator) mode: all-terms customer list (lazy) + one customer's invoices,
// paginated + searchable.
export const fetchInternalCustomers = () => call(API.internalCustomers, {}, 'GET')

export const fetchInternalCustomerInvoices = (customer, { start = 0, pageLength = 50, search = '' } = {}) =>
  call(API.internalCustomerInvoices, { customer, start, page_length: pageLength, search }, 'GET')

export const promptMpesa = (invoice, phone) =>
  call(API.promptMpesa, { invoice, phone: phone || '' })

// STK an existing request (e.g. a bundle) for its full amount.
export const promptRequestMpesa = (request, phone) =>
  call(API.promptRequest, { request, phone: phone || '' })

export const saveCustomerContact = (request, phone) =>
  call(API.saveContact, { request, phone })

export const paymentState = (request) => call(API.paymentState, { request }, 'GET')

// Bundle several of ONE customer's invoices into a single payment. The server
// re-checks that every invoice belongs to `customer` (and one company).
export const createBundle = (customer, invoices) =>
  call(API.createBundle, { customer, invoices: JSON.stringify(invoices) })

// Request-detail view (a bundle or single request).
export const fetchRequestDetail = (request) => call(API.requestDetail, { request }, 'GET')
export const getPaymentLink = (request) => call(API.paymentLink, { request })
export const regeneratePaymentLink = (request) => call(API.regenerateLink, { request })
// Cancel an unpaid bundle (the operator backed out) so its invoices return.
export const discardBundle = (request) => call(API.discardBundle, { request })

// start_checkout (POST) ensures the request + token and returns the hosted
// checkout URL; the caller navigates there.
export const startCheckout = (invoice) => call(API.startCheckout, { invoice })
