import { defineConfig } from 'vite'
import path from 'path'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

// The frappeui plugin wires the dev proxy to the Frappe backend, injects Jinja
// boot data into the built entry page, and writes that entry to the app's www/
// folder (collect_app.html) which Frappe serves at /collect.
export default defineConfig({
  plugins: [
    frappeui({
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: true,
      buildConfig: {
        indexHtmlPath: '../ipay/www/collect.html',
        emptyOutDir: true,
      },
    }),
    vue(),
  ],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
})
