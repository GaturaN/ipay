<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createBundle, fetchCustomerCollection } from '@/data/collection'
import { formatKES } from '@/utils/format'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'

const route = useRoute()
const router = useRouter()
const customer = route.params.customer
const driver = route.query.driver || '' // scope the detail to the driver picked on the list

const customerName = ref('')
const invoices = ref([])
const enableRedirect = ref(false)
const canBundle = ref(false)
const mpesaMax = ref(0)
const loading = ref(true)
const loadError = ref(false)
const creatingBundle = ref(false)
const collectError = ref(false)
const prompting = ref(null)

// Operators may tick a subset to collect only some invoices; nothing ticked = collect all.
const selected = ref([])
const selectable = computed(() => canBundle.value && invoices.value.length > 1)

const total = computed(() =>
  invoices.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)
const selectedTotal = computed(() =>
  selected.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)

// Narrow the shown invoices by number; "Collect all" still covers the whole balance.
const search = ref('')
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return invoices.value
  return invoices.value.filter((inv) => inv.name.toLowerCase().includes(query))
})

const isSelected = (inv) => selected.value.some((i) => i.name === inv.name)

function toggleSelect(inv) {
  selected.value = isSelected(inv)
    ? selected.value.filter((i) => i.name !== inv.name)
    : [...selected.value, inv]
}

const clearSelection = () => (selected.value = [])

async function load() {
  loading.value = true
  loadError.value = false
  clearSelection()
  try {
    const data = await fetchCustomerCollection(customer, driver)
    customerName.value = data.customer_name || customer
    invoices.value = data.invoices || []
    enableRedirect.value = Boolean(data.enable_redirect)
    canBundle.value = Boolean(data.can_bundle)
    mpesaMax.value = data.mpesa_max || 0
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function promptInvoice(inv) {
  prompting.value = {
    name: inv.name,
    label: `${inv.customer_name} · ${inv.name}`,
    phone: inv.customer_phone || '',
    kind: 'invoice',
  }
}

// Bundle the given invoices into one payment, then land on the bundle's detail page to
// prompt the full amount (or split it). Nothing ticked collects the whole balance.
async function collect(names) {
  if (!names.length) return
  creatingBundle.value = true
  collectError.value = false
  try {
    const res = await createBundle(customer, names)
    if (res?.request) router.push({ name: 'Request', params: { name: res.request } })
    else collectError.value = true
  } catch {
    collectError.value = true
  } finally {
    creatingBundle.value = false
  }
}
const collectNow = () =>
  collect((selected.value.length ? selected.value : invoices.value).map((inv) => inv.name))

function onPaid(name) {
  invoices.value = invoices.value.filter((inv) => inv.name !== name)
  selected.value = selected.value.filter((inv) => inv.name !== name)
  if (!invoices.value.length) router.push({ name: 'Collect' })
}

onMounted(load)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-xl flex-col gap-4 p-4 pb-10 md:max-w-4xl">
    <button
      type="button"
      class="flex items-center gap-1 self-start text-sm font-medium text-ink/70"
      @click="router.push({ name: 'Collect' })"
    >
      ‹ All customers
    </button>

    <div v-if="loadError" class="py-16 text-center">
      <p class="font-display text-ink/70">Couldn't load — check your connection.</p>
      <button
        type="button"
        class="mt-3 h-11 rounded-xl bg-mpesa px-5 font-semibold text-white"
        @click="load"
      >
        Retry
      </button>
    </div>

    <template v-else>
    <section class="rounded-2xl bg-ink px-5 py-4 text-paper">
      <p class="truncate font-display text-lg font-bold">{{ customerName }}</p>
      <p class="mt-1 font-mono text-3xl font-semibold tabular-nums">{{ formatKES(total) }}</p>
      <p class="text-sm text-paper/60">
        {{ invoices.length }} invoice{{ invoices.length === 1 ? '' : 's' }} outstanding
      </p>
    </section>

    <div v-if="canBundle && invoices.length > 1" class="flex gap-2">
      <button
        type="button"
        class="h-14 flex-1 rounded-xl bg-mpesa text-lg font-semibold text-white transition active:scale-[.98] disabled:opacity-50"
        :disabled="creatingBundle"
        @click="collectNow"
      >
        {{
          creatingBundle
            ? '…'
            : selected.length
              ? `Collect ${selected.length} — ${formatKES(selectedTotal)}`
              : `Collect all — ${formatKES(total)}`
        }}
      </button>
      <button
        v-if="selected.length"
        type="button"
        class="h-14 shrink-0 rounded-xl border border-hairline px-5 font-medium text-ink/70"
        @click="clearSelection"
      >
        Clear
      </button>
    </div>
    <p v-if="collectError" class="-mt-2 px-1 text-sm text-danger">
      Couldn't start the collection — try again.
    </p>
    <p v-if="selectable && !selected.length" class="-mt-2 px-1 text-xs text-ink/60">
      Tick invoices to collect only some.
    </p>

    <input
      v-if="invoices.length > 1"
      v-model="search"
      type="search"
      aria-label="Search this customer's invoices"
      placeholder="Search invoice number…"
      class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40"
    />

    <div v-if="loading" class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div v-for="n in 3" :key="n" class="h-28 animate-pulse rounded-xl bg-ink/5" />
    </div>
    <p v-else-if="!filtered.length" class="py-16 text-center font-display text-ink/70">
      No invoices match.
    </p>
    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <InvoiceCard
        v-for="inv in filtered"
        :key="inv.name"
        :invoice="inv"
        :enable-redirect="enableRedirect"
        :mpesa-max="mpesaMax"
        :selectable="selectable"
        :selected="isSelected(inv)"
        :actions-disabled="selected.length > 0"
        @prompt="promptInvoice(inv)"
        @toggle-select="toggleSelect(inv)"
      />
    </div>
    </template>

    <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" @changed="load" />
  </main>
</template>
