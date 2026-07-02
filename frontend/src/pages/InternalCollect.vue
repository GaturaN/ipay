<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchCollectionStats, fetchInternalCustomers } from '@/data/collection'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import CustomerListShell from '@/components/CustomerListShell.vue'

const route = useRoute()

// Internal (operator) mode: every customer who owes, all payment terms, newest-invoice
// customer first. The list is loaded once (one aggregate call); a customer's invoices are
// fetched only when opened.
const customers = ref([])
const listLoading = ref(true)
const loadError = ref(false)
const notPermitted = ref(false) // a collector reached internal mode — it's operator-only

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const drivers = ref([])
const driver = ref(route.query.driver || '') // restored when returning from a detail page
const paymentTerms = ref([])
const paymentTerm = ref(route.query.payment_term || '')

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return customers.value
  return customers.value.filter((c) => c.customer_name.toLowerCase().includes(query))
})

const emptyMessage = computed(() =>
  search.value.trim()
    ? 'No customers match your search.'
    : 'No customers with an outstanding balance.',
)

async function loadCustomers() {
  listLoading.value = true
  loadError.value = false
  notPermitted.value = false
  try {
    const data = await fetchInternalCustomers(driver.value, paymentTerm.value)
    customers.value = data.customers || []
    drivers.value = data.drivers || []
    paymentTerms.value = data.payment_terms || []
  } catch (e) {
    if (e?.exc_type === 'PermissionError' || e?.response?.status === 403) notPermitted.value = true
    else loadError.value = true
  } finally {
    listLoading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await fetchCollectionStats(driver.value, true)
  } finally {
    statsLoading.value = false
  }
}

// The driver/term filters are server-side (they scope each customer's balance), so re-fetch.
function refreshAll() {
  loadCustomers()
  loadStats()
}

useResumeRefresh(refreshAll) // re-pull when the PWA returns to the foreground
onMounted(refreshAll)
</script>

<template>
  <CustomerListShell
    container-class="max-w-5xl"
    title="Collect Payments"
    :collected-today="stats.collected_today"
    :outstanding-today="stats.outstanding_today"
    :remaining="filtered.length"
    count-label="customers"
    :stats-loading="statsLoading"
    :list-loading="listLoading"
    :load-error="loadError"
    :not-permitted="notPermitted"
    :customers="filtered"
    :empty-message="emptyMessage"
    card-route-name="InternalCustomer"
    :card-driver="driver"
    :card-payment-term="paymentTerm"
    @retry="loadCustomers"
  >
    <template #filters>
      <input
        v-model="search"
        type="search"
        aria-label="Search customers"
        placeholder="Search customer…"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:max-w-sm"
      />
      <select
        v-if="drivers.length"
        v-model="driver"
        aria-label="Filter by driver"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-3 text-sm text-ink focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:w-56"
        @change="refreshAll"
      >
        <option value="">All drivers</option>
        <option v-for="d in drivers" :key="d" :value="d">{{ d }}</option>
      </select>
      <select
        v-if="paymentTerms.length"
        v-model="paymentTerm"
        aria-label="Filter by payment term"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-3 text-sm text-ink focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:w-48"
        @change="refreshAll"
      >
        <option value="">All terms</option>
        <option v-for="t in paymentTerms" :key="t" :value="t">{{ t }}</option>
      </select>
    </template>
  </CustomerListShell>
</template>
