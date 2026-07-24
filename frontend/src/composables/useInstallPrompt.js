import { onMounted, onUnmounted, ref } from 'vue'
import { useSession } from '@/stores/session'
import { getPlatform, isMobileOrTablet, isStandalone } from '@/utils/device'
import { safeGet, safeSet } from '@/utils/storage'

// Re-nudge at most this often: show it, and if it's ignored or dismissed don't show it
// again for two weeks. Keyed per user so a shared device nudges each collector once.
const SNOOZE_MS = 14 * 24 * 60 * 60 * 1000

export function useInstallPrompt() {
  const session = useSession()
  const visible = ref(false)
  const platform = ref(getPlatform())
  const canNativeInstall = ref(false)
  let deferredPrompt = null

  const who = () => session.user || 'anon'
  const snoozeKey = () => `ipay:install-nudge:snoozed-at:${who()}`
  const installedKey = () => `ipay:install-nudge:installed:${who()}`

  function shouldShow() {
    if (!isMobileOrTablet()) return false // phones/tablets only, never a laptop
    if (isStandalone()) return false // already running as an installed app
    if (safeGet(installedKey())) return false // installed earlier this device/user
    const snoozedAt = Number(safeGet(snoozeKey()) || 0)
    return !snoozedAt || Date.now() - snoozedAt > SNOOZE_MS
  }

  // Chromium fires this when the app is installable; stash it so one tap can open the native
  // install dialog. With the service worker currently self-destroying this may never fire —
  // the banner then falls back to manual "how to install" instructions.
  function onBeforeInstallPrompt(e) {
    e.preventDefault()
    deferredPrompt = e
    canNativeInstall.value = true
  }
  function onAppInstalled() {
    safeSet(installedKey(), '1')
    visible.value = false
  }

  async function install() {
    if (!deferredPrompt) return null
    deferredPrompt.prompt()
    const { outcome } = await deferredPrompt.userChoice
    deferredPrompt = null
    canNativeInstall.value = false
    if (outcome === 'accepted') {
      safeSet(installedKey(), '1')
      visible.value = false
    }
    return outcome
  }

  // Dismiss ("✕") means "not now" — snooze for the window rather than hiding forever.
  function snooze() {
    safeSet(snoozeKey(), String(Date.now()))
    visible.value = false
  }

  onMounted(() => {
    window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt)
    window.addEventListener('appinstalled', onAppInstalled)
    if (shouldShow()) visible.value = true
  })
  onUnmounted(() => {
    window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt)
    window.removeEventListener('appinstalled', onAppInstalled)
  })

  return { visible, platform, canNativeInstall, install, snooze }
}
