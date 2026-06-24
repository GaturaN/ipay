<script setup>
import { onUnmounted, ref, watch } from 'vue'
import {
  paymentState,
  promptMpesa,
  promptRequestMpesa,
  saveCustomerContact,
} from '@/data/collection'

// Drives one M-Pesa STK prompt for a target — either a single invoice or an
// existing request (a bundle, charged for its full amount). The number is ALWAYS
// shown (pre-filled) so the operator confirms or changes it before any charge.
// After sending, the request is polled until paid / partial / failed / timeout.
const props = defineProps({
  // null = hidden. { name, label, phone, kind: 'invoice' | 'request' }
  target: { type: Object, default: null },
})
const emit = defineEmits(['close', 'paid'])

const phone = ref('')
const busy = ref(false)
const message = ref(null) // { tone, text }
let pollTimer = null

const toneClass = {
  info: 'text-blue-700',
  success: 'text-green-700',
  warn: 'text-amber-700',
  error: 'text-red-700',
}

watch(
  () => props.target,
  (target) => {
    phone.value = target?.phone || ''
    busy.value = false
    message.value = null
    stopPolling()
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
    message.value = { tone: 'info', text: 'Prompt sent — waiting for payment…' }
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
        settle('warn', 'Paid, but the amount differs — the team will reconcile it.')
      } else if (state.failed) {
        settle('error', 'Payment failed. Please try again.')
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

onUnmounted(stopPolling)
</script>

<template>
  <div
    v-if="target"
    class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    @click.self="$emit('close')"
  >
    <div class="w-full max-w-md rounded-2xl bg-white p-5">
      <h2 class="text-lg font-semibold text-gray-900">Prompt M-Pesa</h2>
      <p class="mt-0.5 truncate text-sm text-gray-500">{{ target.label }}</p>

      <FormControl
        v-model="phone"
        class="mt-4"
        type="tel"
        label="M-Pesa number to charge"
        placeholder="e.g. 0712345678"
      />
      <p class="mt-1 text-xs text-gray-400">Confirm or change the number before sending.</p>

      <p v-if="message" class="mt-3 text-sm" :class="toneClass[message.tone]">
        {{ message.text }}
      </p>

      <div class="mt-5 flex gap-2">
        <Button class="flex-1" @click="$emit('close')">Close</Button>
        <Button variant="solid" theme="green" class="flex-1" :loading="busy" @click="send">
          Send prompt
        </Button>
      </div>
    </div>
  </div>
</template>
