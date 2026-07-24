// Device/environment checks for the install nudge. Installing a PWA ("Add to Home Screen")
// is a phone/tablet gesture, so the nudge must never appear on a laptop or desktop.

// True only for a phone or tablet — not a laptop, even a touchscreen one.
// A touchscreen laptop's PRIMARY pointer is its mouse/trackpad (pointer: fine), so the
// coarse-pointer check excludes it; a phone or tablet's primary pointer is coarse.
export function isMobileOrTablet() {
  if (typeof window === 'undefined') return false
  const nav = window.navigator
  const ua = nav.userAgent || ''
  // iPadOS 13+ masquerades as desktop Safari ("Macintosh"); a Mac reporting more than one
  // touch point is really an iPad. A genuine Mac reports maxTouchPoints 0.
  const isIPad = /Macintosh/.test(ua) && nav.maxTouchPoints > 1
  if (isIPad) return true
  const mobileUA = /Android|iPhone|iPod|Windows Phone|webOS|BlackBerry|Mobile/i.test(ua)
  const coarsePointer = window.matchMedia?.('(pointer: coarse)')?.matches
  const hasTouch = nav.maxTouchPoints > 0
  return Boolean(mobileUA && hasTouch && coarsePointer)
}

// Already launched as an installed app (from the home screen) — no point nudging.
export function isStandalone() {
  if (typeof window === 'undefined') return false
  return Boolean(
    window.matchMedia?.('(display-mode: standalone)')?.matches ||
      window.navigator.standalone === true, // iOS Safari's non-standard flag
  )
}

// Which install instructions to show. iOS gives no install API, so it is always manual.
export function getPlatform() {
  const nav = window.navigator
  const ua = nav.userAgent || ''
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && nav.maxTouchPoints > 1)) return 'ios'
  if (/Android/.test(ua)) return 'android'
  return 'other'
}
