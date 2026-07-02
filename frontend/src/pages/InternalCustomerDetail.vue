<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createBundle, fetchInternalCustomerInvoices } from '@/data/collection'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import { useInvoiceSelection } from '@/composables/useInvoiceSelection'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'
import CustomerMoneyHeader from '@/components/CustomerMoneyHeader.vue'
import CollectBar from '@/components/CollectBar.vue'
import ErrorRetry from '@/components/ErrorRetry.vue'

const PAGE = 50

const route = useRoute()
const router = useRouter()
const customer = route.params.customer
const driver = route.query.driver || '' // scope the detail to the driver picked on the list
const paymentTerm = route.query.payment_term || '' // and to the payment term picked on the list

const customerName = ref('')
const invoices = ref([])
const total = ref(0)
const count = ref(0)
const hasMore = ref(false)
const enableRedirect = ref(false)
const mpesaMax = ref(0)

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
// stays for one-offs. Ticking only makes sense at 3+ invoices — 1 has nothing to bundle
// and 2 are already covered by "Collect all" (count is the customer's full total).
const { selected, isSelected, toggleSelect, clearSelection, dropSelected, selectedTotal } =
  useInvoiceSelection()
const selectable = computed(() => count.value > 2)

// Over the M-Pesa cap with no card fallback a bundle can't be paid (and hides its invoices
// ~30 min) — block it and let the operator collect invoices individually.
const bundleAmount = computed(() => (selected.value.length ? selectedTotal.value : total.value))
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
    const data = await fetchInternalCustomerInvoices(customer, {
      start: reset ? 0 : invoices.value.length,
      pageLength: PAGE,
      search: search.value.trim(),
      driver,
      paymentTerm,
    })
    if (seq !== loadSeq) return // a newer load/search superseded this response — drop it
    customerName.value = data.customer_name || customer
    total.value = data.total_outstanding
    count.value = data.invoice_count
    enableRedirect.value = Boolean(data.enable_redirect)
    mpesaMax.value = data.mpesa_max || 0
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
        query: {
          from: 'internal',
          customer,
          ...(driver ? { driver } : {}),
          ...(paymentTerm ? { payment_term: paymentTerm } : {}),
        },
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
  collect((selected.value.length ? selected.value : invoices.value).map((inv) => inv.name))

// "Collect all" only when the whole balance is on screen: no more pages AND no active
// search (a search narrows the loaded rows, so "all" would bundle just the matches).
const canCollectAll = computed(
  () => !hasMore.value && invoices.value.length > 1 && !search.value.trim(),
)

const toList = () =>
  router.push({
    name: 'Internal',
    query: { ...(driver ? { driver } : {}), ...(paymentTerm ? { payment_term: paymentTerm } : {}) },
  })

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

useResumeRefresh(() => load(true)) // re-pull when the PWA returns to the foreground
onMounted(() => load(true))
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-6xl flex-col gap-4 p-4 pb-10">
    <button
      type="button"
      class="flex items-center gap-1 self-start text-sm font-medium text-ink/70"
      @click="toList"
    >
      ‹ All customers
    </button>

    <ErrorRetry v-if="loadError" @retry="load(true)" />

    <template v-else>
      <CustomerMoneyHeader
        :name="customerName"
        :total="total"
        :count="count"
        :term="paymentTerm || 'all terms'"
      />

      <CollectBar
        :show-bar="selected.length > 0 || canCollectAll"
        :selected-count="selected.length"
        :selected-total="selectedTotal"
        :total="total"
        :creating-bundle="creatingBundle"
        :bundle-blocked="bundleBlocked"
        :mpesa-max="mpesaMax"
        :collect-error="collectError"
        :show-tick-hint="selectable && !selected.length"
        @collect="collectNow"
        @clear="clearSelection"
      />

      <input
        v-model="search"
        type="search"
        aria-label="Search this customer's invoices"
        placeholder="Search invoice number…"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40"
        @input="onSearch"
      />

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
            :mpesa-max="mpesaMax"
            :selectable="selectable"
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
          :aria-busy="loadingMore"
          @click="load(false)"
        >
          {{ loadingMore ? 'Loading…' : 'Load more' }}
        </button>
      </template>

      <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" @changed="load(true)" />
    </template>
  </main>
</template>
