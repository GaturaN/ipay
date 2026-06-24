<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { paymentState, promptMpesa, saveCustomerContact } from '@/data/collection'

// Drives one M-Pesa STK prompt: send it, capture a number if none is on file,
// then poll the request until it is paid, partial, failed, or times out.
const props = defineProps({
  invoice: { type: Object, default: null }, // null = hidden
})
const emit = defineEmits(['close', 'paid'])

const phone = ref('')
const askPhone = ref(false)
const busy = ref(false)
const message = ref(null) // { tone, text }
let pollTimer = null

const toneClass = {
  info: 'text-blue-700',
  success: 'text-green-700',
  warn: 'text-amber-700',
  error: 'text-red-700',
}

// Reset whenever the dialog opens on a new invoice (or closes).
watch(
  () => props.invoice,
  () => {
    phone.value = ''
    askPhone.value = false
    busy.value = false
    message.value = null
    stopPolling()
  },
)

async function send() {
  if (!props.invoice) return
  busy.value = true
  message.value = { tone: 'info', text: 'Sending M-Pesa prompt…' }
  try {
    const res = await promptMpesa(props.invoice.name, phone.value)
    if (res.status === 'missing_phone') {
      askPhone.value = true
      busy.value = false
      message.value = { tone: 'warn', text: 'No number on file — enter one to charge.' }
      return
    }
    if (res.status === 'error') {
      busy.value = false
      message.value = { tone: 'error', text: res.message || 'Could not send the prompt.' }
      return
    }
    // Sent. Persist a newly-entered number for next time (best-effort).
    if (phone.value && res.request) {
      saveCustomerContact(res.request, phone.value).catch(() => {})
    }
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
        v-if="askPhone"
        v-model="phone"
        class="mt-4"
        type="tel"
        label="M-Pesa number"
        placeholder="e.g. 0712345678"
      />

      <p v-if="message" class="mt-3 text-sm" :class="toneClass[message.tone]">
        {{ message.text }}
      </p>

      <div class="mt-5 flex gap-2">
        <Button class="flex-1" @click="$emit('close')">Close</Button>
        <Button
          variant="solid"
          theme="green"
          class="flex-1"
          :loading="busy"
          @click="send"
        >
          {{ askPhone ? 'Charge number' : 'Send prompt' }}
        </Button>
      </div>
    </div>
  </div>
</template>
