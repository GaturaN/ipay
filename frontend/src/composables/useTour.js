import { nextTick } from 'vue'
import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import { useSession } from '@/stores/session'
import { safeGet, safeSet } from '@/utils/storage'

// A first-run walkthrough of a page. It runs once per user, then never again (the "seen"
// flag persists in localStorage), and can be closed at any step via the ✕ or the backdrop —
// closing still counts as seen, so we don't nag on the next visit. Keyed per user so a
// shared device walks each collector through once.
const seenKey = (key, user) => `ipay:tour-seen:${key}:${user || 'anon'}`

export function useTour() {
  const session = useSession()

  function hasSeen(key) {
    return Boolean(safeGet(seenKey(key, session.user)))
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

    const markSeen = () => safeSet(seenKey(key, session.user), '1')
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
