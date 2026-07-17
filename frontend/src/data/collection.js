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
  salesCustomers: 'ipay.www.collect_payments.sales_customers',
  salesCustomerInvoices: 'ipay.www.collect_payments.sales_customer_invoices',
  collectionStats: 'ipay.www.collect_payments.collection_stats',
  promptMpesa: 'ipay.ipay.main.utils.ipay_redirect.prompt_mpesa',
  promptRequest: 'ipay.ipay.main.utils.ipay_redirect.prompt_request_mpesa',
  saveContact: 'ipay.ipay.main.utils.ipay_redirect.save_customer_contact',
  invoiceNotes: 'ipay.ipay.main.utils.ipay_redirect.invoice_notes',
  addInvoiceNote: 'ipay.ipay.main.utils.ipay_redirect.add_invoice_note',
  paymentState: 'ipay.ipay.main.utils.ipay_redirect.payment_state',
  createBundle: 'ipay.ipay.main.utils.ipay_redirect.create_bundle',
  requestDetail: 'ipay.ipay.main.utils.ipay_redirect.request_detail',
  paymentLink: 'ipay.ipay.main.utils.ipay_redirect.get_payment_link',
  regenerateLink: 'ipay.ipay.main.utils.ipay_redirect.regenerate_payment_link',
  discardBundle: 'ipay.ipay.main.utils.ipay_redirect.discard_bundle',
  startCheckout: 'ipay.ipay.main.utils.ipay_redirect.start_checkout',
  startRequestCheckout: 'ipay.ipay.main.utils.ipay_redirect.start_request_checkout',
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
export const fetchInternalCustomers = (driver, paymentTerm, salesPerson) =>
  call(
    API.internalCustomers,
    { driver: driver || '', payment_term: paymentTerm || '', sales_person: salesPerson || '' },
    'GET',
  )

export const fetchInternalCustomerInvoices = (
  customer,
  { start = 0, pageLength = 50, search = '', driver = '', paymentTerm = '', salesPerson = '' } = {},
) =>
  call(
    API.internalCustomerInvoices,
    {
      customer,
      start,
      page_length: pageLength,
      search,
      driver,
      payment_term: paymentTerm,
      sales_person: salesPerson,
    },
    'GET',
  )

// Sales mode (all terms): a sales user's OWN book, or every book for their manager. The
// server resolves a locked caller from their login and ignores salesPerson for them, so it
// only ever filters a manager's view.
export const fetchSalesCustomers = (paymentTerm, salesPerson) =>
  call(
    API.salesCustomers,
    { payment_term: paymentTerm || '', sales_person: salesPerson || '' },
    'GET',
  )

export const fetchSalesCustomerInvoices = (
  customer,
  { start = 0, pageLength = 50, search = '', paymentTerm = '', salesPerson = '' } = {},
) =>
  call(
    API.salesCustomerInvoices,
    {
      customer,
      start,
      page_length: pageLength,
      search,
      payment_term: paymentTerm,
      sales_person: salesPerson,
    },
    'GET',
  )

export const promptMpesa = (invoice, phone) =>
  call(API.promptMpesa, { invoice, phone: phone || '' })

// STK an existing request (e.g. a bundle) for its full amount.
export const promptRequestMpesa = (request, phone) =>
  call(API.promptRequest, { request, phone: phone || '' })

export const saveCustomerContact = (request, phone) =>
  call(API.saveContact, { request, phone })

// Collection notes on an invoice — plain text; the server escapes on write and unescapes here.
export const fetchInvoiceNotes = (invoice) => call(API.invoiceNotes, { invoice }, 'GET')
export const addInvoiceNote = (invoice, note) => call(API.addInvoiceNote, { invoice, note })

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

// Hosted checkout for an existing request/bundle (Pay via iPay on the request page).
export const startRequestCheckout = (request) => call(API.startRequestCheckout, { request })
