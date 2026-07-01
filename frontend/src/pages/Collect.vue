<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createBundle, fetchCollectionList, fetchCollectionStats } from '@/data/collection'
import { formatKES } from '@/utils/format'
import RoundHeader from '@/components/RoundHeader.vue'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'

const router = useRouter()

const invoices = ref([])
const drivers = ref([])
const enableRedirect = ref(false)
const canBundle = ref(false)
const listLoading = ref(true)

const stats = ref({ collected_today: 0, outstanding_today: 0 })
const statsLoading = ref(false)

const search = ref('')
const driver = ref('')

const prompting = ref(null)

const selected = ref([])
const creatingBundle = ref(false)

const bundleCustomer = computed(() => selected.value[0]?.customer || null)
const sameCustomer = computed(() => new Set(selected.value.map((i) => i.customer)).size <= 1)
const bundleTotal = computed(() =>
  selected.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return invoices.value.filter((inv) => {
    const matchesDriver = !driver.value || (inv.drivers || []).includes(driver.value)
    const haystack = `${inv.name} ${inv.customer_name} ${inv.delivery_note}`.toLowerCase()
    return matchesDriver && (!query || haystack.includes(query))
  })
})

function promptInvoice(inv) {
  prompting.value = {
    name: inv.name,
    label: `${inv.customer_name} · ${inv.name}`,
    phone: inv.customer_phone || '',
    kind: 'invoice',
  }
}

const isSelected = (inv) => selected.value.some((i) => i.name === inv.name)

function toggleSelect(inv) {
  selected.value = isSelected(inv)
    ? selected.value.filter((i) => i.name !== inv.name)
    : [...selected.value, inv]
}

const clearSelection = () => (selected.value = [])

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
  invoices.value = invoices.value.filter((inv) => inv.name !== name)
  loadStats()
}

function resync() {
  loadList()
  loadStats()
}

onMounted(() => {
  loadList()
  loadStats()
})
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-xl flex-col gap-4 p-4 pb-28">
    <h1 class="pt-1 font-display text-2xl font-bold tracking-tight text-ink">Collect</h1>

    <RoundHeader
      :collected-today="stats.collected_today"
      :outstanding-today="stats.outstanding_today"
      :remaining="filtered.length"
      :loading="statsLoading"
    />

    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        v-model="search"
        type="search"
        aria-label="Search collections"
        placeholder="Search customer, invoice or note…"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40"
      />
      <select
        v-if="drivers.length"
        v-model="driver"
        aria-label="Filter by driver"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-3 text-sm text-ink focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:w-48"
        @change="loadStats"
      >
        <option value="">All drivers</option>
        <option v-for="d in drivers" :key="d" :value="d">{{ d }}</option>
      </select>
    </div>

    <div v-if="listLoading" class="space-y-3 pt-1">
      <div v-for="n in 4" :key="n" class="h-24 animate-pulse rounded-xl bg-ink/5" />
    </div>
    <p v-else-if="!filtered.length" class="py-16 text-center font-display text-ink/70">
      All collected — nothing outstanding for you.
    </p>
    <div v-else class="divide-y divide-hairline rounded-2xl bg-white px-4">
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

    <div
      v-if="selected.length"
      class="fixed inset-x-0 bottom-0 z-40 border-t border-hairline bg-paper/95 p-3 backdrop-blur"
    >
      <div class="mx-auto flex max-w-xl items-center gap-3">
        <div class="min-w-0 flex-1 text-sm">
          <template v-if="sameCustomer">
            <span class="font-semibold text-ink">{{ selected.length }} selected</span>
            <span class="font-mono tabular-nums text-ink/70"> · {{ formatKES(bundleTotal) }}</span>
          </template>
          <span v-else class="font-medium text-owed">
            Bundling is per customer — select one customer at a time.
          </span>
        </div>
        <button type="button" class="h-11 rounded-xl px-4 font-medium text-ink/70" @click="clearSelection">
          Clear
        </button>
        <button
          v-if="sameCustomer"
          type="button"
          class="h-11 rounded-xl bg-mpesa px-5 font-semibold text-white disabled:opacity-50"
          :disabled="creatingBundle"
          @click="createBundleNow"
        >
          {{ creatingBundle ? '…' : 'Pay together' }}
        </button>
      </div>
    </div>

    <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" @changed="resync" />
  </main>
</template>
