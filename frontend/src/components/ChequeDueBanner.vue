<script setup>
import { formatKES } from '@/utils/format'

// Cheques accounts have flagged to collect. Two shapes, one banner:
//  - `dues` (a list): the collect-list banner — each customer is a link into their page.
//  - `due` (one object): the customer-page notice, with a button to collect it right now.
// Renders nothing when there is neither, so callers can drop it in unconditionally.
defineProps({
  dues: { type: Array, default: () => [] },
  due: { type: Object, default: null },
  // Routing context for the list links — the same the customer cards are built from.
  routeName: { type: String, default: 'Customer' },
  driver: { type: String, default: '' },
  paymentTerm: { type: String, default: '' },
  salesPerson: { type: String, default: '' },
})
defineEmits(['collect'])
</script>

<template>
  <!-- List mode: the cheques routed here, each a link into the customer. -->
  <div v-if="dues.length" class="rounded-2xl border border-owed/30 bg-owed/10 px-3 py-3">
    <p class="flex items-center gap-2 font-mono text-xs font-bold uppercase tracking-wide text-owed">
      <span class="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-owed px-1.5 text-[11px] text-white">
        {{ dues.length }}
      </span>
      Cheque{{ dues.length === 1 ? '' : 's' }} to collect
    </p>
    <div class="mt-2 flex flex-col gap-2">
      <router-link
        v-for="d in dues"
        :key="d.name"
        :to="{
          name: routeName,
          params: { customer: d.customer },
          query: {
            ...(driver ? { driver } : {}),
            ...(paymentTerm ? { payment_term: paymentTerm } : {}),
            ...(salesPerson ? { sales_person: salesPerson } : {}),
          },
        }"
        class="flex items-center justify-between gap-3 rounded-xl border border-owed/20 bg-white/70 px-3 py-2 transition-colors active:bg-white"
      >
        <span class="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink">
          {{ d.customer_name || d.customer }}
        </span>
        <span class="flex shrink-0 items-center gap-2">
          <span class="font-mono text-xs font-semibold tabular-nums text-owed">
            {{ d.expected_amount ? formatKES(d.expected_amount) : 'amount TBC' }}
          </span>
          <svg viewBox="0 0 20 20" class="h-4 w-4 text-owed/70" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m7.5 5 5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
      </router-link>
    </div>
  </div>

  <!-- Customer mode: the single flagged cheque, with the collect action. -->
  <div v-else-if="due" class="rounded-2xl border border-owed/30 bg-owed/10 px-4 py-3">
    <p class="font-mono text-xs font-bold uppercase tracking-wide text-owed">Accounts flagged a cheque</p>
    <p v-if="due.expected_amount || due.notes" class="mt-1.5 text-[13px] leading-relaxed text-owed">
      <template v-if="due.expected_amount">
        Expected <span class="font-mono font-semibold tabular-nums">{{ formatKES(due.expected_amount) }}</span>.
      </template>
      <span v-if="due.notes" class="opacity-90">{{ due.notes }}</span>
    </p>
    <button
      type="button"
      class="mt-2.5 h-11 w-full rounded-xl bg-ink text-sm font-semibold text-paper transition active:scale-[.98]"
      @click="$emit('collect')"
    >
      Collect the cheque
    </button>
  </div>
</template>
