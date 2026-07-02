import { onMounted, onUnmounted } from 'vue'

// Re-run fn when the PWA returns to the foreground — the tab becomes visible again,
// or the page is restored from the browser's back-forward cache (e.g. returning from
// the external hosted-checkout redirect). Without this a backgrounded app can show
// stale balances until the operator manually navigates.
export function useResumeRefresh(fn) {
  const onVisible = () => document.visibilityState === 'visible' && fn()
  const onPageShow = (e) => e.persisted && fn()
  onMounted(() => {
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('pageshow', onPageShow)
  })
  onUnmounted(() => {
    document.removeEventListener('visibilitychange', onVisible)
    window.removeEventListener('pageshow', onPageShow)
  })
}
