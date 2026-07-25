import { frappeRequest } from 'frappe-ui'

const M = 'ipay.ipay.main.utils.push'
const post = (method, params) =>
  frappeRequest({ url: `/api/method/${M}.${method}`, method: 'POST', params })

export const subscribePush = (subscription, userAgent) =>
  post('subscribe', { subscription: JSON.stringify(subscription), user_agent: userAgent })

export const unsubscribePush = (endpoint) => post('unsubscribe', { endpoint })

export const setPushPrefs = (endpoint, prefs) =>
  post('set_prefs', { endpoint, prefs: JSON.stringify(prefs) })

export const getPushPrefs = (endpoint) =>
  frappeRequest({ url: `/api/method/${M}.get_prefs`, method: 'GET', params: { endpoint } })

export const sendTestPush = () => post('send_test', {})
