<script setup>
import { formatKES } from '@/utils/format'

defineProps({
  collectedToday: { type: Number, default: 0 },
  outstandingToday: { type: Number, default: 0 },
  loading: Boolean,
})
</script>

<template>
  <div class="grid grid-cols-2 gap-3">
    <div class="rounded-xl border border-gray-200 bg-white p-3">
      <p class="text-xs uppercase tracking-wide text-gray-400">Collected today</p>
      <p class="mt-1 text-lg font-semibold tabular-nums text-green-700">
        {{ loading ? '…' : formatKES(collectedToday) }}
      </p>
    </div>
    <div class="rounded-xl border border-gray-200 bg-white p-3">
      <p class="text-xs uppercase tracking-wide text-gray-400">Yet to collect</p>
      <p class="mt-1 text-lg font-semibold tabular-nums text-amber-700">
        {{ loading ? '…' : formatKES(outstandingToday) }}
      </p>
    </div>
  </div>
</template>
