import './index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { FrappeUI, Button, FormControl, setConfig, frappeRequest } from 'frappe-ui'

import App from './App.vue'
import router from './router'

// Route every frappe-ui resource through Frappe's REST wrapper: it carries the
// session cookie and the CSRF token, so the SPA shares the logged-in desk session.
setConfig('resourceFetcher', frappeRequest)

// The worker is served with Service-Worker-Allowed: /collect so it can be scoped to /collect
// and control the app — iOS only shows push for a worker that controls the app's pages.
const SW_URL = '/api/method/ipay.ipay.main.utils.push.collect_worker'
if (!import.meta.env.DEV && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(SW_URL, { scope: '/collect' }).catch(() => {})
  })
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(FrappeUI)
app.component('Button', Button)
app.component('FormControl', FormControl)

if (import.meta.env.DEV) {
  // In dev the page is served by Vite, so the Jinja-injected boot data is absent.
  // Fetch it from the backend before mounting so window.csrf_token etc. exist.
  frappeRequest({ url: '/api/method/ipay.www.collect.get_context_for_dev' }).then(
    (boot) => {
      Object.assign(window, boot)
      app.mount('#app')
    },
  )
} else {
  app.mount('#app')
}
