# Push Notifications

Opt-in Web Push for the **iPay Collect** PWA. A collector turns notifications on from inside the
app and chooses which of three events they want to hear about. Nothing is sent unless the user
opted in, and each type can be toggled independently.

---

## What a user gets

| Notification | Fires when | Sent to |
|---|---|---|
| **Cheque collection assigned to me** | Accounts assign a *Due* `iPay Cheque Collection` to a driver | that driver's linked User |
| **Successful collection** | A payment finalises as Success / Underpaid / Overpaid | whoever initiated the request |
| **Collection error** | A collection is declined or fails | whoever initiated the request |
| **New note on a customer** | A collector leaves a note in the Collect app | the customer's audience, minus the author (see below) — **off by default** |

"Whoever initiated" is the request's `owner` plus anyone it was assigned to (Frappe *Assign To*).
Tapping a notification opens (or focuses) the Collect app.

**A note's audience** is everyone with a stake in that customer: the **drivers** who deliver to
them, the **sales people** who own them, and anyone already **involved** (assigned a request, or
who left a prior note) — never the author. Operators who can see every customer but aren't
involved are deliberately excluded, and the type is **off by default**, because notes are
frequent. Only notes added in the Collect app trigger it (not Desk-timeline comments).

## Turning it on (for users)

Open Collect → tap the **bell** (top-right of the list) → **Turn on notifications** → allow when
the browser asks. Then tick the types you want, and use **Send a test** to confirm.

- **Android / Chrome / desktop** — works in the browser tab; installing is optional.
- **iPhone / iPad** — Apple only allows push for an **installed** web app. Add Collect to the
  Home Screen first (Share → *Add to Home Screen*), open it from that icon, then turn on
  notifications. A push shows a banner only when the app is **not** in the foreground.

---

## Server setup (one-time, per site)

1. **Install the send library** into the bench env:
   ```bash
   ./env/bin/pip install pywebpush
   ```
   (It is also declared in `pyproject.toml`, so a fresh app install pulls it in.)

2. **Generate a VAPID key pair** (identifies this server to the push services):
   ```python
   import base64
   from cryptography.hazmat.primitives.asymmetric import ec
   b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
   pk = ec.generate_private_key(ec.SECP256R1())
   n = pk.public_key().public_numbers()
   print("public :", b(b"\x04" + n.x.to_bytes(32, "big") + n.y.to_bytes(32, "big")))
   print("private:", b(pk.private_numbers().private_value.to_bytes(32, "big")))
   ```
   Use a **fresh pair per environment** (dev keys should not be reused in production).

3. **Store the keys in site config** (secrets — never committed):
   ```bash
   bench --site <site> set-config ipay_vapid_public_key "<public>"
   bench --site <site> set-config ipay_vapid_private_key "<private>"
   bench --site <site> set-config ipay_vapid_subject "mailto:ops@yourdomain"
   ```

4. **Migrate and restart** so the `iPay Push Subscription` DocType installs and the new code
   loads:
   ```bash
   bench --site <site> migrate
   bench build --app ipay
   bench restart
   ```

Without VAPID keys the feature stays dormant: the bell shows "not set up on the server yet",
and `send_web_push` is a no-op — so a missing key can never break a collection.

---

## How it works

```
iPay Cheque Collection ─┐
finalize_payment ───────┼─► notifications.py ─► send_web_push ─► pywebpush ─► push service ─► SW ─► notification
main.py (Failed) ───────┘        (recipients+copy)  (VAPID sign)   (FCM / APNs)   (showNotification)
```

- **Service worker** — `frontend/src/sw.js` handles `push` (draws the notification) and
  `notificationclick` (focuses/opens the app). It is built by vite-plugin-pwa but **not**
  auto-registered; the app registers it itself (see scope note below).
- **Subscriptions** — the `iPay Push Subscription` DocType stores one row per browser install:
  the push `endpoint`, its keys, and the three per-type preference checkboxes. Endpoints are
  bound to the logged-in user; a user only ever sees or changes their own.
- **Send path** — `ipay.ipay.main.utils.push.send_web_push(users, title, body, notif_type)`
  selects each recipient's subscriptions whose matching preference is on, signs one VAPID
  message with `pywebpush`, and prunes any endpoint the push service reports as gone (404/410).
- **Triggers** — `ipay.ipay.main.utils.notifications` resolves *who* and composes the copy, then
  enqueues `send_web_push` on the background queue so a collection is never slowed by the send.
  It is wired from `hooks.py` (`doc_events` on `iPay Cheque Collection`) and inline in
  `finalize_payment` (success) and `lipana_mpesa` (failure).

### The service-worker scope (why iOS needed a fix)

iOS only surfaces push for an installed web app when the service worker **controls the app's
pages** — i.e. its scope covers `/collect`. A worker served from `/assets/…` (its natural home)
controls `/assets/…`, not `/collect`, so Apple would accept the push (`201`) but nothing would
display. Chrome does not care about this.

Two Frappe constraints shaped the fix: `www/*.js` is Jinja-rendered (which corrupts a compiled
worker), and `/assets` is served by nginx (so no custom headers). The worker is therefore served
by a whitelisted endpoint, `ipay.ipay.main.utils.push.collect_worker`, which returns the built
`sw.js` with the header **`Service-Worker-Allowed: /collect`**. The app registers it at
`/collect` scope (`frontend/src/main.js` and `usePushNotifications.js`), so it controls the app
and iOS delivers.

> **After any worker change, iOS users must remove and re-add the Home-Screen app** for the new
> worker to take effect.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Bell says "not set up on the server yet" | VAPID keys missing, or the server wasn't restarted after they were set. |
| Test says "Test sent" but no notification (iPhone) | App not installed to Home Screen, or the worker changed and the app needs removing & re-adding. Confirm **Settings → Notifications → iPay Collect** is allowed. |
| No banner, but it's in Notification Center | Normal on iOS when the app is in the foreground — background the app to get a banner. |
| Nothing sends at all | `pywebpush` not installed in the bench env. |
| Android user gets nothing | They must grant permission (bell → Turn on); installing is optional there. |

---

## Files

| Area | Path |
|---|---|
| Service worker | `frontend/src/sw.js` |
| Subscribe / prefs / send / worker endpoint | `ipay/ipay/main/utils/push.py` |
| Triggers (who + copy) | `ipay/ipay/main/utils/notifications.py` |
| Subscription store | `ipay/ipay/doctype/ipay_push_subscription/` |
| Client permission + subscribe | `frontend/src/composables/usePushNotifications.js` |
| Bell + preferences UI | `frontend/src/components/NotificationSettings.vue` |
| Public key to the client | `ipay/www/collect.py` (boot) |
| Trigger wiring | `ipay/hooks.py`, `finalize_payment.py`, `main.py` |
