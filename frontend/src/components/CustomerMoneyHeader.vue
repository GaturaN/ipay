<script setup>
import { formatKES } from '@/utils/format'

defineProps({
  name: { type: String, default: '' },
  total: { type: Number, default: 0 },
  count: { type: Number, default: 0 },
  term: { type: String, default: '' }, // internal mode appends the payment term
})
</script>

<template>
  <section class="rounded-2xl bg-ink px-5 py-4 text-paper">
    <p class="truncate font-display text-lg font-bold">{{ name }}</p>
    <p class="mt-1 font-mono text-3xl font-semibold tabular-nums">{{ formatKES(total) }}</p>
    <p class="text-sm text-paper/60">
      {{ count }} invoice{{ count === 1 ? '' : 's' }} outstanding<span v-if="term"> · {{ term }}</span>
    </p>
  </section>
</template>
