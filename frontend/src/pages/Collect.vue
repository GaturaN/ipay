<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createBundle, fetchCollectionList, fetchCollectionStats } from '@/data/collection'
import { formatKES } from '@/utils/format'
import StatCards from '@/components/StatCards.vue'
import InvoiceCard from '@/components/InvoiceCard.vue'
import BundleCard from '@/components/BundleCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'

const router = useRouter()

const invoices = ref([])
const bundles = ref([])
const drivers = ref([])
const enableRedirect = ref(false)
const canBundle = ref(false)
const listLoading = ref(true)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const driver = ref('') // '' = all drivers

// The M-Pesa prompt target for a single invoice (bundles open their detail page).
const prompting = ref(null)

// Bundling (operators only): a bundle must be ONE customer. The operator may
// select freely, but "Pay together" only appears when every selected invoice
// shares a customer — a mixed selection can never be prompted (the server
// enforces this too).
const selected = ref([])
const creatingBundle = ref(false)

const bundleCustomer = computed(() => selected.value[0]?.customer || null)
const sameCustomer = computed(() => new Set(selected.value.map((i) => i.customer)).size <= 1)
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

function openRequest(name) {
  router.push({ name: 'Request', params: { name } })
}

function promptInvoice(inv) {
  prompting.value = {
    name: inv.name,
    label: `${inv.customer_name} · ${inv.name}`,
    phone: inv.customer_phone || '',
    kind: 'invoice',
  }
}

function isSelected(inv) {
  return selected.value.some((i) => i.name === inv.name)
}

function toggleSelect(inv) {
  selected.value = isSelected(inv)
    ? selected.value.filter((i) => i.name !== inv.name)
    : [...selected.value, inv]
}

function clearSelection() {
  selected.value = []
}

async function createBundleNow() {
  if (!selected.value.length || !sameCustomer.value) return
  const names = selected.value.map((i) => i.name)
  creatingBundle.value = true
  try {
    const res = await createBundle(bundleCustomer.value, names)
    if (res?.request) {
      const bundled = new Set(names)
      invoices.value = invoices.value.filter((inv) => !bundled.has(inv.name))
      clearSelection()
      // Land on the bundle's detail page to prompt the full amount, share the
      // link, or split it.
      router.push({ name: 'Request', params: { name: res.request } })
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
    bundles.value = data.bundles || []
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

function onPaid(name) {
  // For an invoice, drop it from the list; for a bundle the invoices were already
  // removed at creation, so this is a no-op besides refreshing the stats.
  invoices.value = invoices.value.filter((inv) => inv.name !== name)
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

    <section v-if="bundles.length">
      <h2 class="text-sm font-medium text-gray-700">Open bundles</h2>
      <div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <BundleCard v-for="b in bundles" :key="b.name" :bundle="b" @open="openRequest(b.name)" />
      </div>
    </section>

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
        :actions-disabled="selected.length > 0"
        @prompt="promptInvoice(inv)"
        @toggle-select="toggleSelect(inv)"
      />
    </div>

    <!-- Bundle bar: pinned to the bottom (always visible) while invoices are
         selected. A mixed-customer selection turns it into a warning with no
         "Pay together" button — bundling is per customer. -->
    <div
      v-if="selected.length"
      class="fixed inset-x-0 bottom-0 z-40 border-t p-3 backdrop-blur"
      :class="sameCustomer ? 'border-gray-200 bg-white/95' : 'border-amber-200 bg-amber-50'"
    >
      <div class="mx-auto flex max-w-5xl items-center gap-3">
        <div class="min-w-0 flex-1 text-sm">
          <template v-if="sameCustomer">
            <span class="font-medium">{{ selected.length }} selected</span>
            <span class="text-gray-500"> · {{ formatKES(bundleTotal) }}</span>
          </template>
          <span v-else class="font-medium text-amber-800">
            {{ selected.length }} selected across different customers — bundling is per customer.
          </span>
        </div>
        <Button @click="clearSelection">Clear</Button>
        <Button
          v-if="sameCustomer"
          variant="solid"
          theme="green"
          :loading="creatingBundle"
          @click="createBundleNow"
        >
          Pay together
        </Button>
      </div>
    </div>

    <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" />
  </main>
</template>
