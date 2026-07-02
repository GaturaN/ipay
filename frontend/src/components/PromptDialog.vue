<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import {
  paymentState,
  promptMpesa,
  promptRequestMpesa,
  saveCustomerContact,
} from '@/data/collection'
import { formatKES } from '@/utils/format'

// One M-Pesa STK prompt for a target (a single invoice or a bundle request). The number and
// the amount are shown so the operator confirms both before charging. On success a "money
// received" screen is held so the operator sees the confirmation before the caller routes on.
const props = defineProps({
  // null = hidden. { name, title, subtitle, phone, amount, kind: 'invoice' | 'request' }
  target: { type: Object, default: null },
})
const emit = defineEmits(['close', 'paid', 'changed'])

const RETURN_AFTER_MS = 5000 // auto-dismiss the success screen if the operator doesn't tap Done

const phone = ref('')
const busy = ref(false)
const message = ref(null) // { tone, text }
const paid = ref(false)
const receipt = ref('')
const dialogRef = ref(null)
let pollTimer = null
let returnTimer = null

const toneBox = {
  info: 'bg-ink/5 text-ink/70',
  success: 'bg-landed/10 text-landed',
  warn: 'bg-owed/10 text-owed',
  error: 'bg-danger/10 text-danger',
}
const waiting = computed(() => busy.value && message.value?.tone === 'info')

// Close on Escape and trap Tab within the dialog (keyboard/AT users can't wander to the
// page behind the modal). On the success screen, Escape acknowledges rather than abandons.
function onKeydown(e) {
  if (e.key === 'Escape') return paid.value ? finishPaid() : emit('close')
  if (e.key !== 'Tab') return
  const items = Array.from(
    dialogRef.value?.querySelectorAll('input, button, [href], [tabindex]:not([tabindex="-1"])') || [],
  ).filter((el) => !el.disabled)
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

watch(
  () => props.target,
  (target) => {
    phone.value = target?.phone || ''
    busy.value = false
    message.value = null
    paid.value = false
    receipt.value = ''
    stopPolling()
    clearReturn()
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
      // Ignore late/overlapping poll responses once success is already handled — otherwise a
      // second in-flight "paid" could schedule a duplicate return timer and emit('paid') twice.
      if (paid.value) return
      if (state.paid) {
        // Hold a "money received" screen; hand back to the caller on Done / auto-timeout.
        settle('success', 'Payment received')
        receipt.value = state.detail || ''
        paid.value = true
        returnTimer = setTimeout(finishPaid, RETURN_AFTER_MS)
        nextTick(() => dialogRef.value?.querySelector('button')?.focus())
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

// Acknowledge the success screen (Done button, backdrop, Escape, or auto-timeout): hand back
// to the caller, which removes the paid invoice and routes on.
function finishPaid() {
  clearReturn()
  emit('paid', props.target?.name)
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

function clearReturn() {
  if (returnTimer) {
    clearTimeout(returnTimer)
    returnTimer = null
  }
}

onUnmounted(() => {
  stopPolling()
  clearReturn()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    v-if="target"
    class="fixed inset-0 z-50 flex items-end justify-center bg-ink/50 p-4 sm:items-center"
    @click.self="paid ? finishPaid() : $emit('close')"
  >
    <div
      ref="dialogRef"
      role="dialog"
      aria-modal="true"
      aria-labelledby="prompt-title"
      class="w-full max-w-md rounded-3xl bg-paper p-6"
    >
      <!-- Success: money received -->
      <div v-if="paid" class="text-center">
        <div class="mx-auto grid h-16 w-16 place-items-center rounded-full bg-landed/15">
          <svg
            viewBox="0 0 24 24"
            class="h-9 w-9 text-landed"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
          >
            <path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <p id="prompt-title" class="mt-4 font-display text-lg font-semibold text-ink">
          Payment received
        </p>
        <p class="mt-1 font-mono text-4xl font-bold tabular-nums text-landed">
          {{ formatKES(target.amount) }}
        </p>
        <p v-if="receipt" class="mx-auto mt-3 max-w-xs text-xs text-ink/60">{{ receipt }}</p>
        <button
          type="button"
          class="mt-6 h-12 w-full rounded-xl bg-ink font-semibold text-paper transition active:scale-[.98]"
          @click="finishPaid"
        >
          Done
        </button>
      </div>

      <!-- Prompt form -->
      <template v-else>
        <p class="font-display text-xs font-semibold uppercase tracking-widest text-ink/60">
          Prompt M-Pesa
        </p>
        <p id="prompt-title" class="mt-1 text-lg font-semibold leading-snug text-ink">
          {{ target.title }}
        </p>
        <p v-if="target.subtitle" class="mt-0.5 break-words text-sm text-ink/60">
          {{ target.subtitle }}
        </p>
        <p v-if="target.amount" class="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink">
          {{ formatKES(target.amount) }}
        </p>

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
            :aria-busy="busy"
            @click="send"
          >
            {{ busy ? 'Waiting…' : 'Send prompt' }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>
