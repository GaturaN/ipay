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
      // We register the worker ourselves (main.js) from a root-served copy, scoped to /collect
      // so it controls the app — iOS only shows push for a worker that controls the app's pages.
      injectRegister: false,
      // Custom service worker (src/sw.js), so it can carry a Web Push `push` /
      // `notificationclick` handler — a generated SW can't. It was previously
      // self-destroying (no push listener, unregisters itself), which made push
      // impossible; that is now off. The SW deliberately does NOT precache the
      // app shell yet (globPatterns empty) — its only job for now is Web Push, so
      // there is no stale-asset risk to manage. Offline precaching can be layered
      // on later by giving the injected manifest real glob patterns.
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
