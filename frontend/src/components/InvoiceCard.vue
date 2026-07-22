<script setup>
import { computed, ref } from 'vue'
import { formatKES, formatDate } from '@/utils/format'
import { startCheckout } from '@/data/collection'

const props = defineProps({
  invoice: { type: Object, required: true },
  enableRedirect: Boolean,
  allowCheque: Boolean,
  chequePerInvoice: Boolean,
  selectable: Boolean,
  selected: Boolean,
  actionsDisabled: Boolean,
  mpesaMax: { type: Number, default: 0 }, // M-Pesa ceiling; 0 = no cap
})
defineEmits(['prompt', 'toggle-select', 'notes', 'cheque'])

const checkoutBusy = ref(false)

// M-Pesa can't process a charge over the ceiling — hide the prompt and steer to card/iPay.
const mpesaBlocked = computed(
  () => props.mpesaMax > 0 && Number(props.invoice.outstanding_amount || 0) > props.mpesaMax,
)

// A cheque can cover part of an invoice; the whole invoice is held until accounts bank it, so
// the notice names the balance that reopens then rather than implying it is collectable now.
const chequeIsPartial = computed(
  () => Number(props.invoice.awaiting_cheque || 0) < Number(props.invoice.outstanding_amount || 0),
)

// The row truncates the note visually; a screen reader gets the count and the note itself.
const noteLabel = computed(() => {
  const count = props.invoice.note_count || 0
  if (!count) return 'Add a note'
  return `${count} note${count === 1 ? '' : 's'}. Latest: ${props.invoice.note_latest}`
})

async function payViaIpay() {
  checkoutBusy.value = true
  try {
    const res = await startCheckout(props.invoice.name)
    if (res?.url) window.location = res.url
  } finally {
    checkoutBusy.value = false
  }
}
</script>

<template>
  <article
    class="rounded-xl border bg-white p-4 transition-colors"
    :class="selected ? 'border-mpesa bg-mpesa/5' : 'border-hairline'"
  >
    <div class="flex items-start gap-3">
      <button
        v-if="selectable"
        type="button"
        class="-ml-2 grid h-10 w-10 shrink-0 place-items-center"
        :aria-pressed="selected"
        aria-label="Select for bundle"
        @click="$emit('toggle-select')"
      >
        <span
          class="grid h-6 w-6 place-items-center rounded-md border-2 transition-colors"
          :class="selected ? 'border-mpesa bg-mpesa text-white' : 'border-hairline'"
        >
          <svg v-if="selected" viewBox="0 0 20 20" class="h-4 w-4" fill="currentColor">
            <path d="M8 13.5 4.5 10l-1.2 1.2L8 15.9l9-9L15.8 5.7z" />
          </svg>
        </span>
      </button>

      <div class="min-w-0 flex-1">
        <p class="truncate font-display text-base font-semibold text-ink">{{ invoice.name }}</p>
        <span
          v-if="invoice.payment_terms_template"
          class="mt-1 inline-block rounded-md bg-ink/10 px-2 py-0.5 text-[11px] font-semibold text-ink/80"
        >
          {{ invoice.payment_terms_template }}
        </span>
        <p v-if="invoice.due_date" class="mt-0.5 text-xs text-ink/60">
          Due {{ formatDate(invoice.due_date) }}
        </p>
        <p v-if="invoice.delivery_note" class="break-words text-xs text-ink/70">
          {{ invoice.delivery_note }}
        </p>
        <!-- Both people are labelled: two bare names would be indistinguishable. -->
        <p v-if="invoice.driver_name" class="break-words text-xs text-ink/55">
          Driver · {{ invoice.driver_name }}
        </p>
        <p v-if="invoice.sales_person_name" class="break-words text-xs text-ink/55">
          Sales · {{ invoice.sales_person_name }}
        </p>
      </div>

      <p class="shrink-0 font-mono text-xl font-semibold tabular-nums text-owed">
        {{ formatKES(invoice.outstanding_amount) }}
      </p>
    </div>

    <!-- Above the actions: a note is context for the decision to charge, not a footnote to it. -->
    <button
      type="button"
      class="mt-3 flex h-11 w-full items-center gap-2 rounded-xl px-3 text-left text-[13px] font-medium transition-colors"
      :class="
        invoice.note_count
          ? 'bg-paper text-ink/80'
          : 'border border-hairline text-ink/50 active:bg-paper'
      "
      :aria-label="noteLabel"
      @click="$emit('notes')"
    >
      <svg viewBox="0 0 20 20" class="h-[15px] w-[15px] shrink-0" fill="none" stroke="currentColor" stroke-width="1.7">
        <path d="M4 4.5h12v8H8l-4 3.5z" stroke-linejoin="round" />
      </svg>
      <span class="min-w-0 flex-1 truncate">{{ invoice.note_latest || 'Add note' }}</span>
      <span
        v-if="invoice.note_count > 1"
        class="grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full bg-ink/10 px-1.5 text-[11px] font-bold tabular-nums text-ink/75"
      >
        {{ invoice.note_count }}
      </span>
    </button>

    <!-- A cheque is recorded but not yet banked, so the invoice is still open. Charging it again
         would take the money twice — the actions go away entirely until accounts clear it. -->
    <p
      v-if="invoice.awaiting_cheque"
      class="mt-2 flex items-center gap-2 rounded-xl bg-owed/10 px-3 py-2.5 text-[13px] font-medium text-owed"
    >
      <svg viewBox="0 0 20 20" class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.7">
        <rect x="2.5" y="5" width="15" height="10" rx="1.5" />
        <path d="M2.5 9h15" />
      </svg>
      <span>
        Cheque for {{ formatKES(invoice.awaiting_cheque) }} with accounts to bank.
        <template v-if="chequeIsPartial">
          The {{ formatKES(Number(invoice.outstanding_amount) - invoice.awaiting_cheque) }} balance
          reopens once they bank it.
        </template>
      </span>
    </p>

    <template v-else>
      <div class="mt-2 flex gap-2">
        <button
          v-if="!mpesaBlocked"
          type="button"
          class="h-12 flex-1 rounded-xl bg-mpesa font-semibold text-white transition active:scale-[.98] disabled:opacity-40"
          :disabled="actionsDisabled"
          @click="$emit('prompt')"
        >
          Prompt M-Pesa
        </button>
        <button
          v-if="enableRedirect"
          type="button"
          class="h-12 flex-1 rounded-xl border border-hairline px-4 font-medium text-ink transition active:scale-[.98] disabled:opacity-40"
          :disabled="actionsDisabled || checkoutBusy"
          :aria-busy="checkoutBusy"
          @click="payViaIpay"
        >
          {{ checkoutBusy ? 'Opening…' : 'Card / other' }}
        </button>
        <button
          v-if="allowCheque && chequePerInvoice"
          type="button"
          class="h-12 shrink-0 rounded-xl border border-hairline px-4 text-sm font-medium text-ink/70 transition active:scale-[.98] disabled:opacity-40"
          :disabled="actionsDisabled"
          @click="$emit('cheque')"
        >
          Cheque
        </button>
      </div>
      <p v-if="mpesaBlocked" class="mt-2 text-xs text-owed">
        M-Pesa isn't available over {{ formatKES(mpesaMax) }}.
        {{ enableRedirect ? 'Use Card / other.' : 'Card checkout is off — contact the internal team.' }}
      </p>
    </template>
  </article>
</template>
