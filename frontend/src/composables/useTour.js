import { nextTick, watch } from 'vue'
import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import { useSession } from '@/stores/session'
import { safeGet, safeSet } from '@/utils/storage'
import { markTourSeen } from '@/data/onboarding'

// A first-run walkthrough of a page. It runs once per user, then never again, and can be closed
// at any step via the ✕ or the backdrop — closing still counts as seen. "Seen" is recorded
// server-side against the user account (boot.tours_seen → window.tours_seen), so it survives a
// cache clear, a new browser, a different device, or a PWA reinstall. localStorage mirrors it
// per browser for an instant check and as a fallback if the server write is missed.
const seenKey = (key, user) => `ipay:tour-seen:${key}:${user || 'anon'}`

// The account-level list from boot, kept in memory so a tour marked seen this session isn't
// replayed on an in-app navigation before the next page load re-reads boot.
const serverSeen = () => (typeof window !== 'undefined' && window.tours_seen) || []

export function useTour() {
  const session = useSession()

  function hasSeen(key) {
    return serverSeen().includes(key) || Boolean(safeGet(seenKey(key, session.user)))
  }

  // steps: [{ element?: string, title, description }]. An element-less step is a centred
  // intro card; steps whose anchor isn't on the page (an empty list, a filter a role never
  // sees) are dropped so the tour never points at nothing.
  async function start(key, steps) {
    if (hasSeen(key)) return
    await nextTick() // let the page (and its list) finish rendering so anchors exist
    const present = steps.filter((s) => !s.element || document.querySelector(s.element))
    // If nothing anchored survives (e.g. the whole list is empty), don't spend the one run.
    if (!present.some((s) => s.element)) return

    const markSeen = () => {
      safeSet(seenKey(key, session.user), '1') // instant, this browser
      if (!serverSeen().includes(key)) {
        window.tours_seen = [...serverSeen(), key] // this session won't replay it
        markTourSeen(key).catch(() => {}) // persist against the account, across devices
      }
    }
    driver({
      showProgress: true,
      popoverClass: 'ipay-tour',
      nextBtnText: 'Next',
      prevBtnText: 'Back',
      doneBtnText: 'Done',
      steps: present.map((s) => ({
        element: s.element,
        popover: { title: s.title, description: s.description },
      })),
      onDestroyed: markSeen, // fires on Done and on close/backdrop alike — persists either way
    }).drive()
  }

  return { start, hasSeen }
}

// Run a page's first-run tour once its content is ready (e.g. the list finished loading), so
// the anchors exist. Fires only on the first ready transition — not on later re-fetches (a
// foreground resume, a filter change). `isReady` is a getter, e.g. () => !loading.value.
export function useFirstRunTour(isReady, key, steps) {
  const { start } = useTour()
  let tried = false
  watch(
    isReady,
    (ready) => {
      if (!ready || tried || !key || !steps.length) return
      tried = true
      start(key, steps)
    },
    { immediate: true },
  )
}
