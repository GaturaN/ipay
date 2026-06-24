import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

// Authentication state for the SPA. The app shares the Frappe desk session, so
// the signed-in user is read from the `user_id` cookie set by Frappe.
export const useSession = defineStore('ipay-collect-session', () => {
  const user = ref(readUserFromCookie())
  const isLoggedIn = computed(() => Boolean(user.value))

  function logout() {
    window.location.href = '/login?redirect-to=/collect'
  }

  return { user, isLoggedIn, logout }
})

function readUserFromCookie() {
  const cookies = new URLSearchParams(document.cookie.split('; ').join('&'))
  const user = cookies.get('user_id')
  return user && user !== 'Guest' ? user : null
}
