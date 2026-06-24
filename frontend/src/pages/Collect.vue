<script setup>
import { computed, onMounted, ref } from 'vue'
import { createBundle, fetchCollectionList, fetchCollectionStats } from '@/data/collection'
import { formatKES } from '@/utils/format'
import StatCards from '@/components/StatCards.vue'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'
import LinkDialog from '@/components/LinkDialog.vue'

const invoices = ref([])
const drivers = ref([])
const enableRedirect = ref(false)
const canBundle = ref(false)
const listLoading = ref(true)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const driver = ref('') // '' = all drivers
const prompting = ref(null) // invoice being prompted, or null

// Bundling (operators only): selection is constrained to a single customer,
// mirroring the server-side rule in create_bundle.
const selected = ref([])
const bundleNote = ref('')
const creatingBundle = ref(false)
const bundleLink = ref(null)

const bundleCustomer = computed(() => selected.value[0]?.customer || null)
const bundleTotal = computed(() =>
  selected.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)

// Search + driver filter run client-side over the loaded list; the stat cards
// re-fetch per driver because "collected today" is computed server-side.
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return invoices.value.filter((inv) => {
    const matchesDriver = !driver.value || (inv.drivers || []).includes(driver.value)
    const haystack = `${inv.name} ${inv.customer_name} ${inv.delivery_note}`.toLowerCase()
    return matchesDriver && (!query || haystack.includes(query))
  })
})

function isSelected(inv) {
  return selected.value.some((i) => i.name === inv.name)
}

function toggleSelect(inv) {
  if (isSelected(inv)) {
    selected.value = selected.value.filter((i) => i.name !== inv.name)
    if (!selected.value.length) bundleNote.value = ''
    return
  }
  if (bundleCustomer.value && inv.customer !== bundleCustomer.value) {
    bundleNote.value = 'Bundling is per customer — clear the selection to switch customers.'
    return
  }
  bundleNote.value = ''
  selected.value = [...selected.value, inv]
}

function clearSelection() {
  selected.value = []
  bundleNote.value = ''
}

async function createBundleNow() {
  if (!selected.value.length) return
  creatingBundle.value = true
  try {
    const names = selected.value.map((i) => i.name)
    const res = await createBundle(bundleCustomer.value, names)
    if (res?.url) {
      const bundled = new Set(names)
      invoices.value = invoices.value.filter((inv) => !bundled.has(inv.name))
      clearSelection()
      loadStats()
      bundleLink.value = res.url
    }
  } finally {
    creatingBundle.value = false
  }
}

async function loadList() {
  listLoading.value = true
  try {
    const data = await fetchCollectionList()
    invoices.value = data.invoices || []
    drivers.value = data.drivers || []
    enableRedirect.value = Boolean(data.enable_redirect)
    canBundle.value = Boolean(data.can_bundle)
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
  invoices.value = invoices.value.filter((inv) => inv.name !== invoiceName)
  loadStats()
}

onMounted(() => {
  loadList()
  loadStats()
})
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-5xl flex-col gap-4 p-4 pb-24">
    <header>
      <h1 class="text-xl font-semibold text-gray-900">Collect Payment</h1>
      <p class="text-sm text-gray-500">Prompt a customer for payment.</p>
    </header>

    <StatCards
      :collected-today="stats.collected_today"
      :outstanding-today="stats.outstanding_today"
      :loading="statsLoading"
    />

    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        v-model="search"
        type="search"
        placeholder="Search invoice, customer or delivery note…"
        class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
      />
      <select
        v-if="drivers.length"
        v-model="driver"
        class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm sm:w-64"
        @change="loadStats"
      >
        <option value="">All drivers</option>
        <option v-for="d in drivers" :key="d" :value="d">{{ d }}</option>
      </select>
    </div>

    <p v-if="bundleNote" class="text-sm text-amber-700">{{ bundleNote }}</p>

    <p v-if="listLoading" class="py-10 text-center text-sm text-gray-400">Loading…</p>
    <p v-else-if="!filtered.length" class="py-10 text-center text-sm text-gray-400">
      No invoices to collect.
    </p>
    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <InvoiceCard
        v-for="inv in filtered"
        :key="inv.name"
        :invoice="inv"
        :enable-redirect="enableRedirect"
        :selectable="canBundle"
        :selected="isSelected(inv)"
        @prompt="prompting = inv"
        @toggle-select="toggleSelect(inv)"
      />
    </div>

    <!-- Bundle bar: pinned to the bottom while invoices are selected. -->
    <div
      v-if="selected.length"
      class="fixed inset-x-0 bottom-0 z-40 border-t border-gray-200 bg-white/95 p-3 backdrop-blur"
    >
      <div class="mx-auto flex max-w-5xl items-center gap-3">
        <div class="min-w-0 flex-1 text-sm">
          <span class="font-medium">{{ selected.length }} selected</span>
          <span class="text-gray-500"> · {{ formatKES(bundleTotal) }}</span>
        </div>
        <Button @click="clearSelection">Clear</Button>
        <Button variant="solid" theme="green" :loading="creatingBundle" @click="createBundleNow">
          Pay together
        </Button>
      </div>
    </div>

    <PromptDialog :invoice="prompting" @close="prompting = null" @paid="onPaid" />
    <LinkDialog :url="bundleLink" title="Bundle payment link" @close="bundleLink = null" />
  </main>
</template>
