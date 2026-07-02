<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import {
  paymentState,
  promptMpesa,
  promptRequestMpesa,
  saveCustomerContact,
} from '@/data/collection'

// One M-Pesa STK prompt for a target (a single invoice or a bundle request). The
// number is always shown pre-filled so the operator confirms it before charging.
const props = defineProps({
  // null = hidden. { name, label, phone, kind: 'invoice' | 'request' }
  target: { type: Object, default: null },
})
const emit = defineEmits(['close', 'paid', 'changed'])

const phone = ref('')
const busy = ref(false)
const message = ref(null) // { tone, text }
const dialogRef = ref(null)
let pollTimer = null

const toneBox = {
  info: 'bg-ink/5 text-ink/70',
  success: 'bg-landed/10 text-landed',
  warn: 'bg-owed/10 text-owed',
  error: 'bg-danger/10 text-danger',
}
const waiting = computed(() => busy.value && message.value?.tone === 'info')

const onKeydown = (e) => e.key === 'Escape' && emit('close')

watch(
  () => props.target,
  (target) => {
    phone.value = target?.phone || ''
    busy.value = false
    message.value = null
    stopPolling()
    window[target ? 'addEventListener' : 'removeEventListener']('keydown', onKeydown)
    if (target) nextTick(() => dialogRef.value?.querySelector('input')?.focus())
  },
)

function sendPrompt(name, value) {
  return props.target.kind === 'request'
    ? promptRequestMpesa(name, value)
    : promptMpesa(name, value)
}

async function send() {
  if (!props.target) return
  if (!phone.value.trim()) {
    message.value = { tone: 'warn', text: 'Enter the M-Pesa number to charge.' }
    return
  }
  busy.value = true
  message.value = { tone: 'info', text: 'Sending M-Pesa prompt…' }
  try {
    const res = await sendPrompt(props.target.name, phone.value)
    if (res.status === 'missing_phone') {
      busy.value = false
      message.value = { tone: 'warn', text: 'Enter a valid M-Pesa number (e.g. 0712345678).' }
      return
    }
    if (res.status === 'error') {
      busy.value = false
      message.value = { tone: 'error', text: res.message || 'Could not send the prompt.' }
      return
    }
    if (res.request) saveCustomerContact(res.request, phone.value).catch(() => {})
    message.value = { tone: 'info', text: 'Waiting for the customer to enter their PIN…' }
    startPolling(res.request)
  } catch (error) {
    busy.value = false
    message.value = { tone: 'error', text: error.message || 'Something went wrong.' }
  }
}

function startPolling(request) {
  let tries = 0
  pollTimer = setInterval(async () => {
    tries += 1
    try {
      const state = await paymentState(request)
      if (state.paid) {
        settle('success', 'Payment received. Thank you!')
        emit('paid', props.target.name)
      } else if (state.partial) {
        settle('warn', state.detail || 'Paid, but the amount differs — the team will reconcile it.')
        emit('changed')
      } else if (state.failed) {
        // state.detail carries the specific M-Pesa reason (insufficient balance,
        // wrong PIN, cancelled) the backend classified — show it, not just "failed".
        settle('error', state.detail || 'Payment failed. Please try again.')
        emit('changed')
      } else if (tries >= 40) {
        settle('warn', 'Still waiting — it will reflect once the customer pays.')
      }
    } catch {
      // Transient poll error — keep waiting.
    }
  }, 3000)
}

function settle(tone, text) {
  stopPolling()
  busy.value = false
  message.value = { tone, text }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(() => {
  stopPolling()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    v-if="target"
    class="fixed inset-0 z-50 flex items-end justify-center bg-ink/50 p-4 sm:items-center"
    @click.self="$emit('close')"
  >
    <div
      ref="dialogRef"
      role="dialog"
      aria-modal="true"
      aria-labelledby="prompt-title"
      class="w-full max-w-md rounded-3xl bg-paper p-6"
    >
      <p class="font-display text-xs font-semibold uppercase tracking-widest text-ink/60">
        Prompt M-Pesa
      </p>
      <p id="prompt-title" class="mt-1 truncate text-lg font-semibold text-ink">{{ target.label }}</p>

      <FormControl
        v-model="phone"
        class="mt-5"
        type="tel"
        label="M-Pesa number to charge"
        placeholder="e.g. 0712345678"
      />
      <p class="mt-1 text-xs text-ink/70">Confirm or change the number before sending.</p>

      <div
        v-if="message"
        class="mt-4 flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
        :class="toneBox[message.tone]"
      >
        <span v-if="waiting" class="h-2 w-2 shrink-0 animate-ping rounded-full bg-current" />
        <span>{{ message.text }}</span>
      </div>

      <div class="mt-6 flex gap-2">
        <button
          type="button"
          class="h-12 flex-1 rounded-xl border border-hairline font-medium text-ink"
          @click="$emit('close')"
        >
          Close
        </button>
        <button
          type="button"
          class="h-12 flex-1 rounded-xl bg-mpesa font-semibold text-white transition active:scale-[.98] disabled:opacity-40"
          :disabled="busy"
          @click="send"
        >
          {{ busy ? 'Waiting…' : 'Send prompt' }}
        </button>
      </div>
    </div>
  </div>
</template>
