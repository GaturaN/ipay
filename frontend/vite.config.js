import { defineConfig } from 'vite'
import path from 'path'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import { VitePWA } from 'vite-plugin-pwa'

// The frappeui plugin wires the dev proxy to the Frappe backend, injects Jinja
// boot data into the built entry page, and writes that entry to the app's www/
// folder (collect.html) which Frappe serves at /collect. VitePWA adds the web
// app manifest + service worker so the app is installable on a phone.
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
    VitePWA({
      registerType: 'autoUpdate',
      // We register the worker ourselves (main.js) at /collect scope so it controls the app —
      // iOS only shows push for a worker that controls the app's pages.
      injectRegister: false,
      // Custom service worker (src/sw.js) so it can carry a Web Push handler; a generated one
      // can't. No precaching yet (empty globPatterns) — its only job for now is push.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.js',
      injectManifest: {
        globPatterns: [],
      },
      manifest: {
        name: 'iPay Collect',
        short_name: 'iPay Collect',
        description: 'Prompt customers for payment and track collections.',
        display: 'standalone',
        scope: '/collect',
        start_url: '/collect',
        theme_color: '#007a36',
        background_color: '#f2f5f1',
        icons: [
          { src: '/assets/ipay/manifest/manifest-icon-192.maskable.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/assets/ipay/manifest/manifest-icon-192.maskable.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/assets/ipay/manifest/manifest-icon-512.maskable.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/assets/ipay/manifest/manifest-icon-512.maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  build: {
    reportCompressedSize: false,
  },
})
