// injectManifest requires this token even though precaching is off (empty globPatterns).
self.__ipayPrecache = self.__WB_MANIFEST

const ICON = '/assets/ipay/manifest/manifest-icon-192.maskable.png'
const BADGE = '/assets/ipay/manifest/favicon-196.png'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', () => {})

self.addEventListener('push', (event) => {
  const { title, body, tag, url } = readPush(event)
  event.waitUntil(
    self.registration.showNotification(title || 'iPay Collect', {
      body: body || '',
      icon: ICON,
      badge: BADGE,
      tag,
      data: { url: url || '/collect' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(focusOrOpenCollect(event.notification.data?.url || '/collect'))
})

function readPush(event) {
  try {
    return event.data ? event.data.json() : {}
  } catch {
    return { body: event.data ? event.data.text() : '' }
  }
}

async function focusOrOpenCollect(url) {
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  const open = windows.find((client) => client.url.includes('/collect') && 'focus' in client)
  return open ? open.focus() : self.clients.openWindow(url)
}
