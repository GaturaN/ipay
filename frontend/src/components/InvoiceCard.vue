<script setup>
import { computed, ref } from 'vue'
import { formatKES } from '@/utils/format'
import { startCheckout } from '@/data/collection'

const props = defineProps({
  invoice: { type: Object, required: true },
  enableRedirect: Boolean,
  selectable: Boolean,
  selected: Boolean,
  actionsDisabled: Boolean,
})
defineEmits(['prompt', 'toggle-select'])

const checkoutBusy = ref(false)

const meta = computed(() =>
  [props.invoice.name, props.invoice.delivery_note, props.invoice.driver_name]
    .filter(Boolean)
    .join(' · '),
)

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
  <article class="py-4 transition-colors" :class="selected && 'bg-mpesa/5'">
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
        <p class="truncate font-display text-base font-semibold text-ink">
          {{ invoice.customer_name }}
        </p>
        <p class="truncate text-xs text-ink/70">{{ meta }}</p>
      </div>

      <p class="shrink-0 font-mono text-xl font-semibold tabular-nums text-owed">
        {{ formatKES(invoice.outstanding_amount) }}
      </p>
    </div>

    <div class="mt-3 flex gap-2">
      <button
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
        class="h-12 rounded-xl border border-hairline px-4 font-medium text-ink transition active:scale-[.98] disabled:opacity-40"
        :disabled="actionsDisabled || checkoutBusy"
        @click="payViaIpay"
      >
        {{ checkoutBusy ? '…' : 'Card / other' }}
      </button>
    </div>
  </article>
</template>
