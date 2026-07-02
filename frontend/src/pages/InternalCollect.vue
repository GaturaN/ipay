<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchCollectionStats, fetchInternalCustomers } from '@/data/collection'
import RoundHeader from '@/components/RoundHeader.vue'
import CustomerCard from '@/components/CustomerCard.vue'

// Internal (operator) mode: every customer who owes, all payment terms, newest-invoice
// customer first. The list is loaded once (one aggregate call); a customer's invoices
// are fetched only when opened.
const customers = ref([])
const listLoading = ref(true)
const loadError = ref(false)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return customers.value
  return customers.value.filter((c) => c.customer_name.toLowerCase().includes(query))
})

async function loadCustomers() {
  listLoading.value = true
  loadError.value = false
  try {
    const data = await fetchInternalCustomers()
    customers.value = data.customers || []
  } catch {
    loadError.value = true
  } finally {
    listLoading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await fetchCollectionStats('', true)
  } finally {
    statsLoading.value = false
  }
}

onMounted(() => {
  loadCustomers()
  loadStats()
})
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-5xl flex-col gap-4 p-4 pb-10">
    <h1 class="pt-1 font-display text-2xl font-bold tracking-tight text-ink">Collect Payments</h1>

    <RoundHeader
      :collected-today="stats.collected_today"
      :outstanding-today="stats.outstanding_today"
      :remaining="filtered.length"
      count-label="customers"
      :loading="statsLoading"
    />

    <input
      v-model="search"
      type="search"
      aria-label="Search customers"
      placeholder="Search customer…"
      class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:max-w-sm"
    />

    <div v-if="listLoading" class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div v-for="n in 6" :key="n" class="h-20 animate-pulse rounded-xl bg-ink/5" />
    </div>
    <div v-else-if="loadError" class="py-16 text-center">
      <p class="font-display text-ink/70">Couldn't load — check your connection.</p>
      <button
        type="button"
        class="mt-3 h-11 rounded-xl bg-mpesa px-5 font-semibold text-white"
        @click="loadCustomers"
      >
        Retry
      </button>
    </div>
    <p v-else-if="!filtered.length" class="py-16 text-center font-display text-ink/70">
      No customers with an outstanding balance.
    </p>
    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <CustomerCard
        v-for="c in filtered"
        :key="c.customer"
        :customer="c"
        route-name="InternalCustomer"
      />
    </div>
  </main>
</template>
