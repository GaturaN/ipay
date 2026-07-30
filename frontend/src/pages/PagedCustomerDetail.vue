<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createBundle,
  fetchInternalCustomerInvoices,
  fetchSalesCustomerInvoices,
} from '@/data/collection'
import { formatKES } from '@/utils/format'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import { useInvoiceSelection } from '@/composables/useInvoiceSelection'
import { useFirstRunTour } from '@/composables/useTour'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'
import NotesDialog from '@/components/NotesDialog.vue'
import ChequeDialog from '@/components/ChequeDialog.vue'
import ChequeDueBanner from '@/components/ChequeDueBanner.vue'
import CustomerMoneyHeader from '@/components/CustomerMoneyHeader.vue'
import CollectBar from '@/components/CollectBar.vue'
import ErrorRetry from '@/components/ErrorRetry.vue'

const PAGE = 50

// The paginated drill-down behind both big-book lists — internal (every customer) and sales
// (a member's own). They differ only in where the invoices come from and which scope the URL
// carries, so paging, selection, bundling and prompting stay in one place. The field app's
// CustomerDetail is separate: it loads a driver's whole round unpaginated.
const MODES = {
  internal: {
    fetch: fetchInternalCustomerInvoices,
    list: 'Internal',
    back: 'All customers',
    scope: ['driver', 'payment_term', 'sales_person'],
  },
  sales: {
    fetch: fetchSalesCustomerInvoices,
    list: 'Sales',
    back: 'My customers',
    scope: ['payment_term', 'sales_person'],
  },
}

const route = useRoute()
const router = useRouter()
const mode = MODES[route.meta.mode]
const customer = route.params.customer
const paymentTerm = route.query.payment_term || '' // shown in the header; the rest scope silently

// The scope this mode carries in the URL, kept so every navigation away and back preserves it.
const scopeQuery = () =>
  Object.fromEntries(mode.scope.filter((k) => route.query[k]).map((k) => [k, route.query[k]]))

const customerName = ref('')
const invoices = ref([])
const chequeDue = ref(null) // a cheque accounts flagged to collect from this customer
const total = ref(0)
const chequeOnAccount = ref(0)
const count = ref(0)
const hasMore = ref(false)
const enableRedirect = ref(false)
const allowCheque = ref(false)
const chequePerInvoice = ref(true)
const mpesaMax = ref(0)

const loading = ref(true)
const loadError = ref(false)
const loadingMore = ref(false)
const creatingBundle = ref(false)
const collectError = ref(false)
const prompting = ref(null)
const noting = ref(null)
const chequing = ref(null)

const search = ref('')
let searchTimer = null
let loadSeq = 0 // guards against out-of-order load/search/load-more responses

// Operators may tick a subset (across pages) to collect just those; per-invoice prompt
// stays for one-offs. Ticking only makes sense at 3+ invoices — 1 has nothing to bundle
// and 2 are already covered by "Collect all" (count is the customer's full total).
const { selected, isSelected, toggleSelect, clearSelection, dropSelected, selectedTotal } =
  useInvoiceSelection()
const selectable = computed(() => count.value > 2)

// A cheque already in hand is not banked yet, so the invoice still shows its full balance —
// but charging it again would take the money twice. It stays listed, it just cannot be collected.
const collectable = computed(() => invoices.value.filter((inv) => !inv.awaiting_cheque))
const collectableTotal = computed(() =>
  collectable.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)

// Over the M-Pesa cap with no card fallback a bundle can't be paid (and hides its invoices
// ~30 min) — block it and let the operator collect invoices individually.
const bundleAmount = computed(() =>
  selected.value.length ? selectedTotal.value : collectableTotal.value,
)
const bundleBlocked = computed(
  () => !enableRedirect.value && mpesaMax.value > 0 && bundleAmount.value > mpesaMax.value,
)

async function load(reset = true) {
  const seq = ++loadSeq
  if (reset) {
    loading.value = true
    loadError.value = false
  } else {
    loadingMore.value = true
  }
  try {
    // Each mode's fetch destructures only the scope its own endpoint accepts; extras are ignored.
    const data = await mode.fetch(customer, {
      start: reset ? 0 : invoices.value.length,
      pageLength: PAGE,
      search: search.value.trim(),
      driver: route.query.driver || '',
      paymentTerm,
      salesPerson: route.query.sales_person || '',
    })
    if (seq !== loadSeq) return // a newer load/search superseded this response — drop it
    chequeDue.value = data.cheque_due || null
    // With no invoice for this customer the server can only echo the id; the flag carries the name.
    customerName.value =
      (data.invoice_count ? data.customer_name : chequeDue.value?.customer_name) ||
      data.customer_name ||
      customer
    total.value = data.total_outstanding
    count.value = data.invoice_count
    enableRedirect.value = Boolean(data.enable_redirect)
    allowCheque.value = Boolean(data.allow_cheque)
    chequePerInvoice.value = data.cheque_per_invoice !== false
    mpesaMax.value = data.mpesa_max || 0
    chequeOnAccount.value = Number(data.cheque_on_account || 0)
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
    title: inv.customer_name,
    subtitle: inv.name,
    phone: inv.customer_phone || '',
    amount: Number(inv.outstanding_amount || 0),
    kind: 'invoice',
  }
}

async function collect(names) {
  if (!names.length) return
  creatingBundle.value = true
  collectError.value = false
  try {
    const res = await createBundle(customer, names)
    // Tag the origin so the request page's Back returns here (with the same scope).
    if (res?.request)
      router.push({
        name: 'Request',
        params: { name: res.request },
        query: { from: route.meta.mode, customer, ...scopeQuery() },
      })
    else collectError.value = true
  } catch {
    collectError.value = true
  } finally {
    creatingBundle.value = false
  }
}
// Ticked a subset → collect those; nothing ticked → the whole loaded balance.
const collectNow = () =>
  collect((selected.value.length ? selected.value : collectable.value).map((inv) => inv.name))

// "Collect all" only when the whole balance is on screen: no more pages AND no active
// search (a search narrows the loaded rows, so "all" would bundle just the matches).
const canCollectAll = computed(
  () => !hasMore.value && collectable.value.length > 1 && !search.value.trim(),
)

const toList = () => router.push({ name: mode.list, query: scopeQuery() })

function onPaid(name) {
  prompting.value = null // dismiss the success screen
  const paid = invoices.value.find((inv) => inv.name === name)
  invoices.value = invoices.value.filter((inv) => inv.name !== name)
  dropSelected(name)
  // Keep the header in step with the balance and only leave when the WHOLE customer is
  // settled — not merely when the loaded page emptied (a big account holds thousands).
  count.value = Math.max(0, count.value - 1)
  if (paid) total.value = Math.max(0, total.value - Number(paid.outstanding_amount || 0))
  if (count.value <= 0) toList()
  else if (!invoices.value.length) load(true)
}

// A cheque covers the ticked invoices; nothing ticked records it against the customer instead.
function chequeFromBar() {
  // Per-invoice off -> the bar records a customer-level cheque, so no invoice rows go with it.
  const rows = chequePerInvoice.value
    ? selected.value.map((i) => ({ name: i.name, amount: Number(i.outstanding_amount || 0) }))
    : []
  chequeFor(rows, rows.length ? selectedTotal.value : total.value)
}

function chequeFor(rows, outstanding) {
  chequing.value = { customer, customer_name: customerName.value, invoices: rows, outstanding }
}

// A flagged cheque records on account; suggest the expected amount if accounts gave one.
function collectFlaggedCheque() {
  chequeFor([], Number(chequeDue.value?.expected_amount || 0) || total.value)
}

// Mark the cards in place rather than reloading, which would clear the ticked set underneath.
function onChequeRecorded({ invoices: names, amount, covered }) {
  if (!names.length) chequeOnAccount.value += amount
  invoices.value.forEach((inv) => {
    if (covered[inv.name]) inv.awaiting_cheque = covered[inv.name]
  })
  chequeDue.value = null // the flagged cheque is now collected — drop its banner
  clearSelection()
}

// Patch the card in place: reloading the list would clear a ticked bundle and reset paging.
function onNoteSaved({ invoice, count, latest }) {
  const inv = invoices.value.find((i) => i.name === invoice)
  if (inv) {
    inv.note_count = count
    inv.note_latest = latest
  }
}

useResumeRefresh(() => load(true)) // re-pull when the PWA returns to the foreground
onMounted(() => load(true))

// First-run walkthrough of the customer page — where payment is actually prompted. Runs once
// (shared key across every customer page), after invoices load so the anchors exist. Steps
// whose anchor is absent (nothing collectable, no bundle bar) are dropped.
const TOUR_STEPS = [
  {
    element: '[data-tour="prompt"]',
    title: 'Prompt for payment',
    description:
      "Tap M-Pesa to send this invoice's request to the customer's phone — they approve it with their M-Pesa PIN.",
  },
  {
    element: '[data-tour="collect-bar"]',
    title: 'Collect several at once',
    description: 'More than one invoice? Collect them together in a single request.',
  },
]
useFirstRunTour(() => !loading.value, 'customer', TOUR_STEPS)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-6xl flex-col gap-4 p-4 pb-10">
    <button
      type="button"
      class="flex items-center gap-1 self-start text-sm font-medium text-ink/70"
      @click="toList"
    >
      ‹ {{ mode.back }}
    </button>

    <ErrorRetry v-if="loadError" @retry="load(true)" />

    <template v-else>
      <CustomerMoneyHeader
        :name="customerName"
        :total="total"
        :count="count"
        :term="paymentTerm || 'all terms'"
      />

      <ChequeDueBanner :due="chequeDue" @collect="collectFlaggedCheque" />

      <CollectBar
        :show-bar="selected.length > 0 || canCollectAll"
        :selected-count="selected.length"
        :selected-total="selectedTotal"
        :total="collectableTotal"
        :creating-bundle="creatingBundle"
        :bundle-blocked="bundleBlocked"
        :mpesa-max="mpesaMax"
        :collect-error="collectError"
        :show-tick-hint="selectable && !selected.length"
        :show-cheque="allowCheque && count > 0"
        :cheque-per-invoice="chequePerInvoice"
        @collect="collectNow"
        @clear="clearSelection"
        @cheque="chequeFromBar"
      />

      <p v-if="chequeOnAccount" class="-mt-2 rounded-xl bg-owed/10 px-3 py-2.5 text-[13px] font-medium text-owed">
        {{ formatKES(chequeOnAccount) }} already collected by cheque, with accounts to bank. It is
        not tied to an invoice, so check before collecting again.
      </p>

      <input
        v-model="search"
        type="search"
        aria-label="Search this customer's invoices"
        placeholder="Search invoice number…"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40"
        @input="onSearch"
      />

      <div v-if="loading" class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <div v-for="n in 6" :key="n" class="h-44 animate-pulse rounded-xl bg-ink/5" />
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
            :mpesa-max="mpesaMax"
            :selectable="selectable && !inv.awaiting_cheque"
            :selected="isSelected(inv)"
            :actions-disabled="selected.length > 0"
            :allow-cheque="allowCheque"
            :cheque-per-invoice="chequePerInvoice"
            @prompt="promptInvoice(inv)"
            @notes="noting = { invoice: inv.name, customer_name: inv.customer_name }"
            @cheque="chequeFor([{ name: inv.name, amount: Number(inv.outstanding_amount || 0) }], Number(inv.outstanding_amount || 0))"
            @toggle-select="toggleSelect(inv)"
          />
        </div>
        <button
          v-if="hasMore"
          type="button"
          class="mx-auto h-11 rounded-xl border border-hairline px-6 font-medium text-ink disabled:opacity-50"
          :disabled="loadingMore"
          :aria-busy="loadingMore"
          @click="load(false)"
        >
          {{ loadingMore ? 'Loading…' : 'Load more' }}
        </button>
      </template>

      <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" @changed="load(true)" />
      <NotesDialog :target="noting" @close="noting = null" @saved="onNoteSaved" />
      <ChequeDialog :target="chequing" @close="chequing = null" @recorded="onChequeRecorded" />
    </template>
  </main>
</template>
