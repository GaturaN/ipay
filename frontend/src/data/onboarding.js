import { frappeRequest } from 'frappe-ui'

const M = 'ipay.ipay.main.utils.onboarding'

// Record server-side (per user account) that a first-run tour has been seen.
export const markTourSeen = (tour) =>
  frappeRequest({ url: `/api/method/${M}.mark_seen`, method: 'POST', params: { tour } })
