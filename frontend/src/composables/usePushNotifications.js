import { computed, ref } from 'vue'
import {
  getPushPrefs,
  sendTestPush,
  setPushPrefs,
  subscribePush,
  unsubscribePush,
} from '@/data/push'

const SW_URL = '/api/method/ipay.ipay.main.utils.push.collect_worker'
const SW_SCOPE = '/collect'

const DEFAULT_PREFS = {
  notify_cheque_assigned: 1,
  notify_collection_success: 1,
  notify_collection_error: 1,
  notify_comment: 0,
}

function vapidKey(base64) {
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (char) => char.charCodeAt(0))
}

async function swRegistration() {
  const reg = await navigator.serviceWorker.register(SW_URL, { scope: SW_SCOPE })
  if (reg.active) return reg
  await new Promise((resolve) => {
    const worker = reg.installing || reg.waiting
    if (!worker) return resolve()
    worker.addEventListener('statechange', () => worker.state === 'activated' && resolve())
  })
  return reg
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

  const configured = computed(() => Boolean(window.vapid_public_key))
  const blocked = computed(() => permission.value === 'denied')

  async function refresh() {
    if (!supported.value) return
    try {
      const sub = await (await swRegistration()).pushManager.getSubscription()
      subscribed.value = Boolean(sub)
      if (sub) {
        endpoint = sub.endpoint
        prefs.value = (await getPushPrefs(endpoint).catch(() => null)) || { ...DEFAULT_PREFS }
      }
    } catch {
      error.value = ''
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
      const sub = await (await swRegistration()).pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: vapidKey(window.vapid_public_key),
      })
      endpoint = sub.endpoint
      prefs.value = (await subscribePush(sub.toJSON(), navigator.userAgent))?.prefs || {
        ...DEFAULT_PREFS,
      }
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
      const sub = await (await swRegistration()).pushManager.getSubscription()
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

  const testStatus = ref('')
  async function test() {
    testStatus.value = 'sending'
    try {
      const res = await sendTestPush()
      testStatus.value = res && res.sent ? 'sent' : 'none'
    } catch {
      testStatus.value = 'error'
    }
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
    testStatus,
    refresh,
    enable,
    disable,
    updatePref,
    test,
  }
}
