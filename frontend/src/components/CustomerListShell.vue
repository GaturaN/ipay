<script setup>
import RoundHeader from '@/components/RoundHeader.vue'
import CustomerCard from '@/components/CustomerCard.vue'
import ErrorRetry from '@/components/ErrorRetry.vue'

// The shared customer-list screen (field /collect and internal /collect/internal): title,
// today's-round header, a filters row (slotted, since each mode's filters differ), and the
// loading / not-permitted / error / empty / grid states. Each page owns its data + filters
// and passes the rest as props, so behaviour stays per-page.
defineProps({
  containerClass: { type: String, default: '' }, // per-mode max width
  title: { type: String, default: 'Collect' },
  collectedToday: { type: Number, default: 0 },
  outstandingToday: { type: Number, default: 0 },
  remaining: { type: Number, default: 0 },
  countLabel: { type: String, default: 'to collect' },
  statsLoading: Boolean,
  listLoading: Boolean,
  loadError: Boolean,
  notPermitted: Boolean, // internal mode only — a collector reached operator-only mode
  customers: { type: Array, default: () => [] },
  emptyMessage: { type: String, default: '' },
  cardRouteName: { type: String, default: 'Customer' },
  cardDriver: { type: String, default: '' },
  cardPaymentTerm: { type: String, default: '' },
  cardSalesPerson: { type: String, default: '' },
})
defineEmits(['retry'])
</script>

<template>
  <main class="mx-auto flex min-h-full w-full flex-col gap-4 p-4 pb-10" :class="containerClass">
    <h1 class="pt-1 font-display text-2xl font-bold tracking-tight text-ink">{{ title }}</h1>

    <RoundHeader
      :collected-today="collectedToday"
      :outstanding-today="outstandingToday"
      :remaining="remaining"
      :count-label="countLabel"
      :loading="statsLoading"
    />

    <div class="flex flex-col gap-2 sm:flex-row">
      <slot name="filters" />
    </div>

    <div v-if="listLoading" class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div v-for="n in 6" :key="n" class="h-20 animate-pulse rounded-xl bg-ink/5" />
    </div>
    <div v-else-if="notPermitted" class="py-16 text-center">
      <p class="font-display text-ink/70">Internal collection is for operators only.</p>
      <a
        href="/collect"
        class="mt-3 inline-flex h-11 items-center rounded-xl bg-mpesa px-5 font-semibold text-white"
      >
        Go to Collect
      </a>
    </div>
    <ErrorRetry v-else-if="loadError" @retry="$emit('retry')" />
    <p v-else-if="!customers.length" class="py-16 text-center font-display text-ink/70">
      {{ emptyMessage }}
    </p>
    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <CustomerCard
        v-for="c in customers"
        :key="c.customer"
        :customer="c"
        :route-name="cardRouteName"
        :driver="cardDriver"
        :payment-term="cardPaymentTerm"
        :sales-person="cardSalesPerson"
      />
    </div>
  </main>
</template>
