<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import BaseDialog from './BaseDialog.vue'
import { useInstallPrompt } from '@/composables/useInstallPrompt'

// The nudge belongs on the pages a user lands on after login — not over a customer's invoice
// list, where a floating bar would sit on top of the collect action.
const LANDING_ROUTES = ['Collect', 'Sales', 'Internal']

const route = useRoute()
const { visible, platform, canNativeInstall, install, snooze } = useInstallPrompt()
const showGuide = ref(false)

const showBanner = computed(() => visible.value && LANDING_ROUTES.includes(route.name))

// Bound (not a static src) so Vite serves it from the app's runtime asset path rather than
// trying to resolve and bundle it from the frontend source tree at build time.
const APP_ICON = '/assets/ipay/manifest/favicon-196.png'

// Static, per-platform copy — safe to render with v-html (no user input). iOS never gets a
// native prompt; Android does only when the app is installable (see useInstallPrompt).
const GUIDE_STEPS = {
  ios: [
    'Tap the <strong>Share</strong> button in the browser toolbar.',
    'Scroll down and tap <strong>Add to Home Screen</strong>.',
    'Tap <strong>Add</strong> in the top corner.',
  ],
  android: [
    'Tap the <strong>⋮ menu</strong> at the top-right of the browser.',
    'Tap <strong>Install app</strong> (or <strong>Add to Home screen</strong>).',
    'Tap <strong>Install</strong> to confirm.',
  ],
  other: [
    'Open your browser menu.',
    'Choose <strong>Install app</strong> or <strong>Add to Home Screen</strong>.',
    'Confirm to add it to your home screen.',
  ],
}
const steps = computed(() => GUIDE_STEPS[platform.value] || GUIDE_STEPS.other)

async function onPrimary() {
  // When the native install dialog is available, it owns the whole interaction — don't
  // second-guess a user who dismisses it by then showing manual steps.
  if (canNativeInstall.value) return install()
  // No native dialog (iOS always, Android when the SW is self-destroying) → show the steps.
  showGuide.value = true
}
</script>

<template>
  <div v-if="showBanner" class="fixed inset-x-0 bottom-0 z-40 p-3 sm:p-4">
    <div
      class="mx-auto flex max-w-md items-center gap-3 rounded-2xl border border-hairline bg-white p-3 shadow-lg"
    >
      <img :src="APP_ICON" alt="" class="h-10 w-10 shrink-0 rounded-xl" />
      <div class="min-w-0 flex-1">
        <p class="font-display text-sm font-semibold text-ink">Install iPay Collect</p>
        <p class="text-xs text-ink/60">Add it to your home screen for quick, full-screen access.</p>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-xl bg-mpesa px-3 py-2 text-xs font-semibold text-white"
        @click="onPrimary"
      >
        {{ canNativeInstall ? 'Install' : 'How' }}
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        class="shrink-0 rounded-lg p-1.5 text-lg leading-none text-ink/40"
        @click="snooze"
      >
        ✕
      </button>
    </div>
  </div>

  <BaseDialog
    :open="showGuide"
    labelledby="install-guide-title"
    focus="panel"
    @close="showGuide = false"
  >
    <h2 id="install-guide-title" class="font-display text-lg font-semibold text-ink">
      Add iPay Collect to your home screen
    </h2>
    <ol class="mt-4 space-y-3">
      <li v-for="(step, i) in steps" :key="i" class="flex items-start gap-3 text-sm text-ink">
        <span
          class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-mpesa/10 text-xs font-semibold text-mpesa"
          >{{ i + 1 }}</span
        >
        <span v-html="step" />
      </li>
    </ol>
    <button
      type="button"
      class="mt-6 w-full rounded-xl bg-ink py-2.5 text-sm font-semibold text-white"
      @click="showGuide = false"
    >
      Got it
    </button>
  </BaseDialog>
</template>
