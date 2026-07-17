<script setup>
import { formatKES } from '@/utils/format'

// The collect action for a customer detail: one "Collect all"/"Collect N" button plus the
// per-state hints. Rendered as sibling roots so it drops straight into the page's flex
// column (the hints' -mt-2 tightens them against the button, matching the standalone markup).
defineProps({
  showBar: Boolean, // whether the collect button row is shown at all
  selectedCount: { type: Number, default: 0 },
  selectedTotal: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  creatingBundle: Boolean,
  bundleBlocked: Boolean,
  mpesaMax: { type: Number, default: 0 },
  collectError: Boolean,
  showTickHint: Boolean,
  showCheque: Boolean, // cheque collection is offered even where bundling is not
})
defineEmits(['collect', 'clear', 'cheque'])
</script>

<template>
  <div v-if="showBar" class="flex gap-2">
    <button
      type="button"
      class="h-14 flex-1 rounded-xl bg-mpesa text-lg font-semibold text-white transition active:scale-[.98] disabled:opacity-50"
      :disabled="creatingBundle || bundleBlocked"
      :aria-busy="creatingBundle"
      @click="$emit('collect')"
    >
      {{
        creatingBundle
          ? 'Collecting…'
          : selectedCount
            ? `Collect ${selectedCount} — ${formatKES(selectedTotal)}`
            : `Collect all — ${formatKES(total)}`
      }}
    </button>
    <button
      v-if="selectedCount"
      type="button"
      class="h-14 shrink-0 rounded-xl border border-hairline px-5 font-medium text-ink/70"
      @click="$emit('clear')"
    >
      Clear
    </button>
  </div>
  <p v-if="bundleBlocked" class="-mt-2 px-1 text-xs text-owed">
    This exceeds the M-Pesa limit ({{ formatKES(mpesaMax) }}) and card checkout is off — collect the invoices individually below.
  </p>
  <p v-if="collectError" class="-mt-2 px-1 text-sm text-danger">
    Couldn't start the collection — try again.
  </p>
  <p v-if="showTickHint" class="-mt-2 px-1 text-xs text-ink/60">
    Tick invoices to collect only some.
  </p>
  <!-- Deliberately quiet: cheques are the exception, and M-Pesa stays the obvious action. -->
  <button
    v-if="showCheque"
    type="button"
    class="h-11 rounded-xl border border-hairline bg-white text-sm font-medium text-ink/70 transition active:bg-paper"
    @click="$emit('cheque')"
  >
    {{ selectedCount ? `Cheque for ${selectedCount} — ${formatKES(selectedTotal)}` : 'Collect a cheque' }}
  </button>
</template>
