<script setup>
import { ref, watch } from 'vue'

// Shows a shareable payment link with copy-to-clipboard. `url` null = hidden.
const props = defineProps({
  url: { type: String, default: null },
  title: { type: String, default: 'Payment link' },
})
defineEmits(['close'])

const copied = ref(false)
watch(() => props.url, () => (copied.value = false))

async function copy() {
  try {
    await navigator.clipboard.writeText(props.url)
    copied.value = true
  } catch {
    // Clipboard unavailable (e.g. non-HTTPS) — the link stays selectable above.
  }
}
</script>

<template>
  <div
    v-if="url"
    class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    @click.self="$emit('close')"
  >
    <div class="w-full max-w-md rounded-2xl bg-white p-5">
      <h2 class="text-lg font-semibold text-gray-900">{{ title }}</h2>
      <p class="mt-1 text-sm text-gray-500">Share this link with the customer to pay.</p>

      <div class="mt-3 break-all rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
        {{ url }}
      </div>

      <div class="mt-4 flex gap-2">
        <a :href="url" target="_blank" rel="noopener" class="flex-1">
          <Button class="w-full">Open</Button>
        </a>
        <Button variant="solid" theme="green" class="flex-1" @click="copy">
          {{ copied ? 'Copied ✓' : 'Copy link' }}
        </Button>
      </div>
      <Button class="mt-2 w-full" @click="$emit('close')">Close</Button>
    </div>
  </div>
</template>
