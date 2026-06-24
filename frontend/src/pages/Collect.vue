<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchCollectionList, fetchCollectionStats } from '@/data/collection'
import StatCards from '@/components/StatCards.vue'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'

const invoices = ref([])
const drivers = ref([])
const enableRedirect = ref(false)
const listLoading = ref(true)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const driver = ref('') // '' = all drivers
const prompting = ref(null) // the invoice being prompted, or null

// Search and driver filtering happen client-side over the loaded list; the
// stat cards are re-fetched per driver because "collected today" is server-side.
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return invoices.value.filter((inv) => {
    const matchesDriver = !driver.value || (inv.drivers || []).includes(driver.value)
    const haystack = `${inv.name} ${inv.customer_name} ${inv.delivery_note}`.toLowerCase()
    return matchesDriver && (!query || haystack.includes(query))
  })
})

async function loadList() {
  listLoading.value = true
  try {
    const data = await fetchCollectionList()
    invoices.value = data.invoices || []
    drivers.value = data.drivers || []
    enableRedirect.value = Boolean(data.enable_redirect)
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

function onPaid(invoiceName) {
  // A paid invoice has no outstanding balance, so drop it and refresh the stats.
  invoices.value = invoices.value.filter((inv) => inv.name !== invoiceName)
  loadStats()
}

onMounted(() => {
  loadList()
  loadStats()
})
</script>

<template>
  <main class="mx-auto flex min-h-full max-w-md flex-col gap-4 p-4">
    <header>
      <h1 class="text-xl font-semibold text-gray-900">Collect Payment</h1>
      <p class="text-sm text-gray-500">Prompt a customer for payment.</p>
    </header>

    <StatCards
      :collected-today="stats.collected_today"
      :outstanding-today="stats.outstanding_today"
      :loading="statsLoading"
    />

    <input
      v-model="search"
      type="search"
      placeholder="Search invoice, customer or delivery note…"
      class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
    />

    <select
      v-if="drivers.length"
      v-model="driver"
      class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
      @change="loadStats"
    >
      <option value="">All drivers</option>
      <option v-for="d in drivers" :key="d" :value="d">{{ d }}</option>
    </select>

    <p v-if="listLoading" class="py-10 text-center text-sm text-gray-400">Loading…</p>
    <p v-else-if="!filtered.length" class="py-10 text-center text-sm text-gray-400">
      No invoices to collect.
    </p>
    <div v-else class="flex flex-col gap-3">
      <InvoiceCard
        v-for="inv in filtered"
        :key="inv.name"
        :invoice="inv"
        :enable-redirect="enableRedirect"
        @prompt="prompting = inv"
      />
    </div>

    <PromptDialog :invoice="prompting" @close="prompting = null" @paid="onPaid" />
  </main>
</template>
