<script setup>
import { ref } from 'vue'
import { formatKES } from '@/utils/format'
import { startCheckout } from '@/data/collection'

const props = defineProps({
  invoice: { type: Object, required: true },
  enableRedirect: Boolean,
  selectable: Boolean, // operators only — drives the bundle checkbox
  selected: Boolean,
  actionsDisabled: Boolean, // true while a bundle is being built — no per-invoice actions
})
defineEmits(['prompt', 'toggle-select'])

const checkoutBusy = ref(false)

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
  <div
    class="rounded-xl border bg-white p-4"
    :class="selected ? 'border-green-500 ring-1 ring-green-500' : 'border-gray-200'"
  >
    <div class="flex items-start gap-3">
      <input
        v-if="selectable"
        type="checkbox"
        class="mt-1 h-5 w-5 shrink-0"
        :checked="selected"
        @change="$emit('toggle-select')"
      />
      <div class="min-w-0 flex-1">
        <p class="truncate font-medium text-gray-900">{{ invoice.customer_name }}</p>
        <p class="truncate text-sm text-gray-500">{{ invoice.name }}</p>
        <p v-if="invoice.delivery_note" class="truncate text-xs text-gray-400">
          DN: {{ invoice.delivery_note }}
        </p>
        <p v-if="invoice.driver_name" class="truncate text-xs text-gray-400">
          {{ invoice.driver_name }}
        </p>
      </div>
      <p class="shrink-0 font-semibold tabular-nums text-gray-900">
        {{ formatKES(invoice.outstanding_amount) }}
      </p>
    </div>

    <div class="mt-3 flex gap-2">
      <Button
        variant="solid"
        theme="green"
        class="flex-1"
        :disabled="actionsDisabled"
        @click="$emit('prompt')"
      >
        Prompt M-Pesa
      </Button>
      <Button
        v-if="enableRedirect"
        variant="subtle"
        class="flex-1"
        :disabled="actionsDisabled"
        :loading="checkoutBusy"
        @click="payViaIpay"
      >
        Pay via iPay
      </Button>
    </div>
  </div>
</template>
