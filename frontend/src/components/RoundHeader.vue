<script setup>
import { computed } from 'vue'
import { formatKES } from '@/utils/format'

const props = defineProps({
  collectedToday: { type: Number, default: 0 },
  outstandingToday: { type: Number, default: 0 },
  remaining: { type: Number, default: 0 },
  loading: Boolean,
})

const progress = computed(() => {
  const total = props.collectedToday + props.outstandingToday
  return total ? Math.round((props.collectedToday / total) * 100) : 0
})
</script>

<template>
  <section class="rounded-2xl bg-ink px-5 py-4 text-paper">
    <p class="font-display text-xs font-semibold uppercase tracking-widest text-paper/60">
      Today's round
    </p>
    <p class="mt-1 font-mono text-3xl font-semibold tabular-nums">
      {{ loading ? '—' : formatKES(collectedToday) }}
    </p>
    <p class="text-sm text-paper/60">collected</p>

    <div class="mt-3 h-1.5 overflow-hidden rounded-full bg-paper/15">
      <div
        class="h-full rounded-full bg-landed transition-[width] duration-500"
        :style="{ width: progress + '%' }"
      />
    </div>
    <div class="mt-2 flex justify-between font-mono text-xs tabular-nums text-paper/70">
      <span>{{ formatKES(outstandingToday) }} to go</span>
      <span>{{ remaining }} to collect</span>
    </div>
  </section>
</template>
