<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchCollectionCustomers, fetchCollectionStats } from '@/data/collection'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import RoundHeader from '@/components/RoundHeader.vue'
import CustomerCard from '@/components/CustomerCard.vue'

const route = useRoute()

const customers = ref([])
const drivers = ref([])
const listLoading = ref(true)
const loadError = ref(false)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const driver = ref(route.query.driver || '') // restored when returning from a detail page

// The driver filter is applied server-side (it scopes each customer's total), so this
// only narrows the loaded list — by customer name, invoice number, or delivery note.
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return customers.value
  return customers.value.filter(
    (c) =>
      c.customer_name.toLowerCase().includes(query) ||
      (c.keywords || []).some((k) => k.toLowerCase().includes(query)),
  )
})

const invoiceCount = computed(() =>
  filtered.value.reduce((sum, c) => sum + (c.invoice_count || 0), 0),
)

async function loadCustomers() {
  listLoading.value = true
  loadError.value = false
  try {
    const data = await fetchCollectionCustomers(driver.value)
    customers.value = data.customers || []
    drivers.value = data.drivers || []
  } catch {
    loadError.value = true
  } finally {
    listLoading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await fetchCollectionStats(driver.value)
  } finally {
    statsLoading.value = false
  }
}

function onDriverChange() {
  loadCustomers()
  loadStats()
}

function refreshAll() {
  loadCustomers()
  loadStats()
}

useResumeRefresh(refreshAll) // re-pull when the PWA returns to the foreground
onMounted(refreshAll)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-xl flex-col gap-4 p-4 pb-10 md:max-w-4xl">
    <h1 class="pt-1 font-display text-2xl font-bold tracking-tight text-ink">Collect</h1>

    <RoundHeader
      :collected-today="stats.collected_today"
      :outstanding-today="stats.outstanding_today"
      :remaining="invoiceCount"
      :loading="statsLoading"
    />

    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        v-model="search"
        type="search"
        aria-label="Search customer, invoice or delivery note"
        placeholder="Search customer, invoice or DN…"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40"
      />
      <select
        v-if="drivers.length"
        v-model="driver"
        aria-label="Filter by driver"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-3 text-sm text-ink focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:w-48"
        @change="onDriverChange"
      >
        <option value="">All drivers</option>
        <option v-for="d in drivers" :key="d" :value="d">{{ d }}</option>
      </select>
    </div>

    <div v-if="listLoading" class="grid grid-cols-1 gap-3 pt-1 md:grid-cols-2">
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
      {{ search.trim() ? 'No customers match your search.' : 'All collected — no customers owe you.' }}
    </p>
    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <CustomerCard v-for="c in filtered" :key="c.customer" :customer="c" :driver="driver" />
    </div>
  </main>
</template>
