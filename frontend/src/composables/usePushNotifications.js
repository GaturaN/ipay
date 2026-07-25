import { computed, ref } from 'vue'
import {
  getPushPrefs,
  sendTestPush,
  setPushPrefs,
  subscribePush,
  unsubscribePush,
} from '@/data/push'

// The service worker is registered at its own asset scope (see PR: SW foundation), which does
// NOT control /collect — so navigator.serviceWorker.ready (which waits for the SW controlling
// THIS page) never resolves here. We fetch the registration directly instead.
const SW_URL = '/assets/ipay/frontend/sw.js'
const SW_SCOPE = '/assets/ipay/frontend/'

const DEFAULT_PREFS = {
  notify_cheque_assigned: 1,
  notify_collection_success: 1,
  notify_collection_error: 1,
}

// VAPID public key (base64url) → the Uint8Array the Push API wants as applicationServerKey.
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i)
  return out
}

export function usePushNotifications() {
  const supported = ref(
    typeof window !== 'undefined' &&
      'serviceWorker' in navigator &&
      'PushManager' in window &&
      'Notification' in window,
  )
  const permission = ref(supported.value ? Notification.permission : 'unsupported')
  const subscribed = ref(false)
  const busy = ref(false)
  const error = ref('')
  const prefs = ref({ ...DEFAULT_PREFS })
  let endpoint = ''

  // Server-side keys present? Without them the browser can't subscribe.
  const configured = computed(() => Boolean(window.vapid_public_key))
  // Permission actively denied — the user must re-enable in browser settings; we can't reprompt.
  const blocked = computed(() => permission.value === 'denied')

  async function registration() {
    const reg = await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE })
    if (reg.active) return reg
    // First install — wait for it to activate before subscribing.
    await new Promise((resolve) => {
      const sw = reg.installing || reg.waiting
      if (!sw) return resolve()
      sw.addEventListener('statechange', () => sw.state === 'activated' && resolve())
    })
    return reg
  }

  // Read current state so the panel opens showing the truth (subscribed? which prefs?).
  async function refresh() {
    if (!supported.value) return
    try {
      const reg = await registration()
      const sub = await reg.pushManager.getSubscription()
      subscribed.value = Boolean(sub)
      if (sub) {
        endpoint = sub.endpoint
        prefs.value = (await getPushPrefs(endpoint).catch(() => null)) || { ...DEFAULT_PREFS }
      }
    } catch {
      // Non-fatal — the panel just falls back to the enable button.
    }
  }

  async function enable() {
    error.value = ''
    if (!supported.value) return
    if (!configured.value) {
      error.value = 'Notifications are not set up on the server yet.'
      return
    }
    busy.value = true
    try {
      permission.value = await Notification.requestPermission()
      if (permission.value !== 'granted') return
      const reg = await registration()
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(window.vapid_public_key),
      })
      endpoint = sub.endpoint
      const res = await subscribePush(sub.toJSON(), navigator.userAgent)
      prefs.value = res?.prefs || { ...DEFAULT_PREFS }
      subscribed.value = true
    } catch {
      error.value = 'Could not turn on notifications — please try again.'
    } finally {
      busy.value = false
    }
  }

  async function disable() {
    busy.value = true
    try {
      const reg = await registration()
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        await unsubscribePush(sub.endpoint).catch(() => {})
        await sub.unsubscribe()
      }
      subscribed.value = false
      endpoint = ''
    } finally {
      busy.value = false
    }
  }

  async function updatePref(key, value) {
    prefs.value = { ...prefs.value, [key]: value ? 1 : 0 }
    if (endpoint) await setPushPrefs(endpoint, prefs.value).catch(() => {})
  }

  async function test() {
    await sendTestPush().catch(() => {})
  }

  return {
    supported,
    configured,
    permission,
    blocked,
    subscribed,
    busy,
    error,
    prefs,
    refresh,
    enable,
    disable,
    updatePref,
    test,
  }
}
