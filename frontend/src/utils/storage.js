// Wrappers around localStorage that never throw. Safari private mode and some in-app
// webviews disable storage, and a one-off tour is not worth crashing the app over — a
// failed read/write just means the flag doesn't persist.
export function safeGet(key) {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function safeSet(key, value) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // storage unavailable — nothing to do; the flag simply won't persist
  }
}
