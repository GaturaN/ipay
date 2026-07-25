/* Service worker for iPay Collect.
 *
 * Built via vite-plugin-pwa's injectManifest strategy. Its only job today is Web Push —
 * receiving push messages and turning them into notifications — so it does not precache the
 * app shell (see vite.config.js: globPatterns is empty). Offline caching can be added later
 * by consuming the precache manifest below with workbox-precaching.
 */

// injectManifest replaces self.__WB_MANIFEST with the precache list (empty for now). It's
// assigned to a global rather than a local so bundler dead-code elimination can't drop the
// reference before workbox performs the injection; it's consumed for real once offline
// precaching is enabled.
self.__ipayPrecache = self.__WB_MANIFEST

// Activate a new SW immediately and take control, so a deploy's push handler is live without
// waiting for every tab to close.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

// A registered fetch handler is part of what makes the app installable across browsers (and
// helps Android's install prompt fire). It intentionally does nothing — no respondWith means
// every request falls through to the network unchanged, so nothing is cached or intercepted.
self.addEventListener('fetch', () => {})

const ICON = '/assets/ipay/manifest/manifest-icon-192.maskable.png'
const BADGE = '/assets/ipay/manifest/favicon-196.png'

// A push arrives as JSON: { title, body, tag?, url? }. Fall back gracefully if the payload is
// missing or not JSON, so a malformed message still surfaces something rather than nothing.
self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { body: event.data ? event.data.text() : '' }
  }
  const title = payload.title || 'iPay Collect'
  const options = {
    body: payload.body || '',
    icon: ICON,
    badge: BADGE,
    tag: payload.tag, // same tag collapses duplicates rather than stacking
    data: { url: payload.url || '/collect' },
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

// Tapping a notification focuses an existing collect tab if one is open, otherwise opens it.
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/collect'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes('/collect') && 'focus' in client) return client.focus()
      }
      return self.clients.openWindow(target)
    }),
  )
})
