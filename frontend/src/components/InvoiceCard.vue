<script setup>
import { computed } from 'vue'
import { formatKES } from '@/utils/format'
import { checkoutUrl } from '@/data/collection'

const props = defineProps({
  invoice: { type: Object, required: true },
  enableRedirect: Boolean,
})
defineEmits(['prompt'])

const payUrl = computed(() => checkoutUrl(props.invoice.name))
</script>

<template>
  <div class="rounded-xl border border-gray-200 bg-white p-4">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="truncate font-medium text-gray-900">{{ invoice.customer_name }}</p>
        <p class="truncate text-sm text-gray-500">{{ invoice.name }}</p>
        <p v-if="invoice.driver_name" class="truncate text-xs text-gray-400">
          {{ invoice.driver_name }}
        </p>
      </div>
      <p class="shrink-0 font-semibold tabular-nums text-gray-900">
        {{ formatKES(invoice.outstanding_amount) }}
      </p>
    </div>

    <div class="mt-3 flex gap-2">
      <Button variant="solid" theme="green" class="flex-1" @click="$emit('prompt')">
        Prompt M-Pesa
      </Button>
      <a v-if="enableRedirect" :href="payUrl" class="flex-1">
        <Button variant="subtle" class="w-full">Pay via iPay</Button>
      </a>
    </div>
  </div>
</template>
