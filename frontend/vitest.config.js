import { defineConfig } from 'vite'
import path from 'path'
import vue from '@vitejs/plugin-vue'

// Test-only config, deliberately separate from vite.config.js: that one loads the frappeui
// and PWA plugins, which proxy to a bench and write ../ipay/www/collect.html — neither
// belongs in a test run. The '@' alias is repeated here because tests import through it.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.js'],
  },
})
