import './index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { FrappeUI, Button, FormControl, setConfig, frappeRequest } from 'frappe-ui'

import App from './App.vue'
import router from './router'

// Route every frappe-ui resource through Frappe's REST wrapper: it carries the
// session cookie and the CSRF token, so the SPA shares the logged-in desk session.
setConfig('resourceFetcher', frappeRequest)

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
