<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchCollectionCustomers, fetchCollectionStats } from '@/data/collection'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import CustomerListShell from '@/components/CustomerListShell.vue'

const route = useRoute()

const customers = ref([])
const drivers = ref([])
const chequeDues = ref([])
const listLoading = ref(true)
const loadError = ref(false)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const driver = ref(route.query.driver || '') // restored when returning from a detail page

// The driver filter is server-side (it scopes each customer's total); this only narrows the
// loaded list — by customer name, invoice number, or delivery note.
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

const emptyMessage = computed(() =>
  search.value.trim() ? 'No customers match your search.' : 'All collected — no customers owe you.',
)

async function loadCustomers() {
  listLoading.value = true
  loadError.value = false
  try {
    const data = await fetchCollectionCustomers(driver.value)
    customers.value = data.customers || []
    drivers.value = data.drivers || []
    chequeDues.value = data.cheque_dues || []
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

function refreshAll() {
  loadCustomers()
  loadStats()
}

useResumeRefresh(refreshAll) // re-pull when the PWA returns to the foreground
onMounted(refreshAll)
</script>

<template>
  <CustomerListShell
    container-class="max-w-xl md:max-w-4xl"
    title="Collect"
    :collected-today="stats.collected_today"
    :outstanding-today="stats.outstanding_today"
    :remaining="invoiceCount"
    :stats-loading="statsLoading"
    :list-loading="listLoading"
    :load-error="loadError"
    :customers="filtered"
    :cheque-dues="chequeDues"
    :empty-message="emptyMessage"
    :card-driver="driver"
    @retry="loadCustomers"
  >
    <template #filters>
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
        @change="refreshAll"
      >
        <option value="">All drivers</option>
        <option v-for="d in drivers" :key="d" :value="d">{{ d }}</option>
      </select>
    </template>
  </CustomerListShell>
</template>
