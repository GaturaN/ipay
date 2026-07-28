import { frappeRequest } from 'frappe-ui'

const M = 'ipay.ipay.main.utils.onboarding'

export const markTourSeen = (tour) =>
  frappeRequest({ url: `/api/method/${M}.mark_seen`, method: 'POST', params: { tour } })
