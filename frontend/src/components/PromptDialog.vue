<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { paymentState, promptMpesa, saveCustomerContact } from '@/data/collection'

// Drives one M-Pesa STK prompt. The number is ALWAYS shown (pre-filled with the
// customer's on-file number) so the operator confirms or changes it before any
// charge — it is never sent silently to a default. After sending, the request is
// polled until it is paid, partial, failed, or times out.
const props = defineProps({
  invoice: { type: Object, default: null }, // null = hidden
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

// Reset and pre-fill with the on-file number whenever a new invoice opens.
watch(
  () => props.invoice,
  (invoice) => {
    phone.value = invoice?.customer_phone || ''
    busy.value = false
    message.value = null
    stopPolling()
  },
)

async function send() {
  if (!props.invoice) return
  if (!phone.value.trim()) {
    message.value = { tone: 'warn', text: 'Enter the M-Pesa number to charge.' }
    return
  }
  busy.value = true
  message.value = { tone: 'info', text: 'Sending M-Pesa prompt…' }
  try {
    const res = await promptMpesa(props.invoice.name, phone.value)
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
    // Persist the confirmed number for next time (best-effort; the server only
    // fills a blank Customer number, never overwrites one).
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
        emit('paid', props.invoice.name)
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
    v-if="invoice"
    class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center"
    @click.self="$emit('close')"
  >
    <div class="w-full max-w-md rounded-2xl bg-white p-5">
      <h2 class="text-lg font-semibold text-gray-900">Prompt M-Pesa</h2>
      <p class="mt-0.5 truncate text-sm text-gray-500">
        {{ invoice.customer_name }} · {{ invoice.name }}
      </p>

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
