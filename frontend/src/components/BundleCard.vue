<script setup>
import { formatKES } from '@/utils/format'

// A tappable open bundle — opens its detail page to prompt / share / split.
defineProps({ bundle: { type: Object, required: true } })
defineEmits(['open'])
</script>

<template>
  <button
    class="w-full rounded-xl border border-gray-200 bg-white p-4 text-left active:bg-gray-50"
    @click="$emit('open')"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="truncate font-medium text-gray-900">{{ bundle.customer_name }}</p>
        <p class="truncate text-sm text-gray-500">
          {{ bundle.name }} · {{ bundle.invoice_count }} invoices · {{ bundle.status }}
        </p>
      </div>
      <p class="shrink-0 font-semibold tabular-nums text-gray-900">
        {{ formatKES(bundle.amount) }}
      </p>
    </div>
  </button>
</template>
