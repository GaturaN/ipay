<script setup>
import { formatKES } from '@/utils/format'

defineProps({
  customer: { type: Object, required: true },
  driver: { type: String, default: '' }, // carried through so the detail stays driver-scoped
})
</script>

<template>
  <router-link
    :to="{ name: 'Customer', params: { customer: customer.customer }, query: driver ? { driver } : {} }"
    class="flex items-center gap-3 rounded-xl border border-hairline bg-white p-4 transition-colors active:bg-mpesa/5"
  >
    <div class="min-w-0 flex-1">
      <p class="truncate font-display text-base font-semibold text-ink">
        {{ customer.customer_name }}
      </p>
      <p class="text-xs text-ink/70">
        {{ customer.invoice_count }} invoice{{ customer.invoice_count === 1 ? '' : 's' }}
      </p>
    </div>
    <p class="shrink-0 font-mono text-xl font-semibold tabular-nums text-owed">
      {{ formatKES(customer.total_outstanding) }}
    </p>
    <svg
      viewBox="0 0 20 20"
      class="h-5 w-5 shrink-0 text-ink/40"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    >
      <path d="m7.5 5 5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </router-link>
</template>
