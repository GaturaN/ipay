<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createBundle, fetchInternalCustomerInvoices } from '@/data/collection'
import { formatKES } from '@/utils/format'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'

const PAGE = 50

const route = useRoute()
const router = useRouter()
const customer = route.params.customer

const customerName = ref('')
const invoices = ref([])
const total = ref(0)
const count = ref(0)
const hasMore = ref(false)
const enableRedirect = ref(false)

const loading = ref(true)
const loadError = ref(false)
const loadingMore = ref(false)
const creatingBundle = ref(false)
const collectError = ref(false)
const prompting = ref(null)

const search = ref('')
let searchTimer = null
let loadSeq = 0 // guards against out-of-order load/search/load-more responses

// Operators may tick a subset (across pages) to collect just those; per-invoice prompt
// stays for one-offs. No blanket "collect all" — a big account holds thousands.
const selected = ref([])
const selectedTotal = computed(() =>
  selected.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)
const isSelected = (inv) => selected.value.some((i) => i.name === inv.name)
function toggleSelect(inv) {
  selected.value = isSelected(inv)
    ? selected.value.filter((i) => i.name !== inv.name)
    : [...selected.value, inv]
}
const clearSelection = () => (selected.value = [])

async function load(reset = true) {
  const seq = ++loadSeq
  if (reset) {
    loading.value = true
    loadError.value = false
  } else {
    loadingMore.value = true
  }
  try {
    const data = await fetchInternalCustomerInvoices(customer, {
      start: reset ? 0 : invoices.value.length,
      pageLength: PAGE,
      search: search.value.trim(),
    })
    if (seq !== loadSeq) return // a newer load/search superseded this response — drop it
    customerName.value = data.customer_name || customer
    total.value = data.total_outstanding
    count.value = data.invoice_count
    enableRedirect.value = Boolean(data.enable_redirect)
    invoices.value = reset ? data.invoices || [] : [...invoices.value, ...(data.invoices || [])]
    hasMore.value = Boolean(data.has_more)
  } catch {
    if (reset && seq === loadSeq) loadError.value = true
  } finally {
    if (seq === loadSeq) {
      loading.value = false
      loadingMore.value = false
    }
  }
}

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => load(true), 300)
}

function promptInvoice(inv) {
  prompting.value = {
    name: inv.name,
    label: `${inv.customer_name} · ${inv.name}`,
    phone: inv.customer_phone || '',
    kind: 'invoice',
  }
}

async function collectSelected() {
  if (!selected.value.length) return
  creatingBundle.value = true
  collectError.value = false
  try {
    const res = await createBundle(customer, selected.value.map((inv) => inv.name))
    if (res?.request) router.push({ name: 'Request', params: { name: res.request } })
    else collectError.value = true
  } catch {
    collectError.value = true
  } finally {
    creatingBundle.value = false
  }
}

function onPaid(name) {
  const paid = invoices.value.find((inv) => inv.name === name)
  invoices.value = invoices.value.filter((inv) => inv.name !== name)
  selected.value = selected.value.filter((inv) => inv.name !== name)
  // Keep the header in step with the balance and only leave when the WHOLE customer is
  // settled — not merely when the loaded page emptied (a big account holds thousands).
  count.value = Math.max(0, count.value - 1)
  if (paid) total.value = Math.max(0, total.value - Number(paid.outstanding_amount || 0))
  if (count.value <= 0) router.push({ name: 'Internal' })
  else if (!invoices.value.length) load(true)
}

onMounted(() => load(true))
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-6xl flex-col gap-4 p-4 pb-10">
    <button
      type="button"
      class="flex items-center gap-1 self-start text-sm font-medium text-ink/70"
      @click="router.push({ name: 'Internal' })"
    >
      ‹ All customers
    </button>

    <div v-if="loadError" class="py-16 text-center">
      <p class="font-display text-ink/70">Couldn't load — check your connection.</p>
      <button
        type="button"
        class="mt-3 h-11 rounded-xl bg-mpesa px-5 font-semibold text-white"
        @click="load(true)"
      >
        Retry
      </button>
    </div>

    <template v-else>
      <section class="rounded-2xl bg-ink px-5 py-4 text-paper">
        <p class="truncate font-display text-lg font-bold">{{ customerName }}</p>
        <p class="mt-1 font-mono text-3xl font-semibold tabular-nums">{{ formatKES(total) }}</p>
        <p class="text-sm text-paper/60">
          {{ count }} invoice{{ count === 1 ? '' : 's' }} outstanding · all terms
        </p>
      </section>

      <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          v-model="search"
          type="search"
          aria-label="Search this customer's invoices"
          placeholder="Search invoice number…"
          class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:max-w-sm"
          @input="onSearch"
        />
        <div v-if="selected.length" class="flex gap-2 sm:ml-auto">
          <button
            type="button"
            class="h-11 rounded-xl bg-mpesa px-5 font-semibold text-white disabled:opacity-50"
            :disabled="creatingBundle"
            @click="collectSelected"
          >
            {{ creatingBundle ? '…' : `Collect ${selected.length} — ${formatKES(selectedTotal)}` }}
          </button>
          <button
            type="button"
            class="h-11 rounded-xl border border-hairline px-4 font-medium text-ink/70"
            @click="clearSelection"
          >
            Clear
          </button>
        </div>
      </div>
      <p v-if="collectError" class="-mt-2 px-1 text-sm text-danger">
        Couldn't start the collection — try again.
      </p>

      <div v-if="loading" class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <div v-for="n in 6" :key="n" class="h-28 animate-pulse rounded-xl bg-ink/5" />
      </div>
      <p v-else-if="!invoices.length" class="py-16 text-center font-display text-ink/70">
        No invoices match.
      </p>
      <template v-else>
        <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          <InvoiceCard
            v-for="inv in invoices"
            :key="inv.name"
            :invoice="inv"
            :enable-redirect="enableRedirect"
            :selectable="true"
            :selected="isSelected(inv)"
            :actions-disabled="selected.length > 0"
            @prompt="promptInvoice(inv)"
            @toggle-select="toggleSelect(inv)"
          />
        </div>
        <button
          v-if="hasMore"
          type="button"
          class="mx-auto h-11 rounded-xl border border-hairline px-6 font-medium text-ink disabled:opacity-50"
          :disabled="loadingMore"
          @click="load(false)"
        >
          {{ loadingMore ? '…' : 'Load more' }}
        </button>
      </template>

      <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" @changed="load(true)" />
    </template>
  </main>
</template>
