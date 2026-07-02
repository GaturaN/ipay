<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createBundle, fetchCustomerCollection } from '@/data/collection'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import { useInvoiceSelection } from '@/composables/useInvoiceSelection'
import InvoiceCard from '@/components/InvoiceCard.vue'
import PromptDialog from '@/components/PromptDialog.vue'
import CustomerMoneyHeader from '@/components/CustomerMoneyHeader.vue'
import CollectBar from '@/components/CollectBar.vue'
import ErrorRetry from '@/components/ErrorRetry.vue'

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

const { selected, isSelected, toggleSelect, clearSelection, dropSelected, selectedTotal } =
  useInvoiceSelection()
const selectable = computed(() => canBundle.value && invoices.value.length > 1)

const total = computed(() =>
  invoices.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
)

// A bundle is charged as one M-Pesa STK (or hosted checkout). Over the cap with no card
// fallback it can't be paid and would hide the invoices ~30 min — block it and let the
// operator collect invoices individually instead.
const bundleAmount = computed(() => (selected.value.length ? selectedTotal.value : total.value))
const bundleBlocked = computed(
  () => !enableRedirect.value && mpesaMax.value > 0 && bundleAmount.value > mpesaMax.value,
)

// Narrow the shown invoices by number; "Collect all" still covers the whole balance.
const search = ref('')
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return invoices.value
  return invoices.value.filter((inv) => inv.name.toLowerCase().includes(query))
})

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
    // Tag the origin so the request page's Back returns to this customer (with driver scope).
    if (res?.request)
      router.push({
        name: 'Request',
        params: { name: res.request },
        query: { from: 'field', customer, ...(driver ? { driver } : {}) },
      })
    else collectError.value = true
  } catch {
    collectError.value = true
  } finally {
    creatingBundle.value = false
  }
}
const collectNow = () =>
  collect((selected.value.length ? selected.value : invoices.value).map((inv) => inv.name))

const toList = () => router.push({ name: 'Collect', query: driver ? { driver } : {} })

function onPaid(name) {
  invoices.value = invoices.value.filter((inv) => inv.name !== name)
  dropSelected(name)
  if (!invoices.value.length) toList()
}

useResumeRefresh(load) // re-pull when the PWA returns to the foreground
onMounted(load)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-xl flex-col gap-4 p-4 pb-10 md:max-w-4xl">
    <button
      type="button"
      class="flex items-center gap-1 self-start text-sm font-medium text-ink/70"
      @click="toList"
    >
      ‹ All customers
    </button>

    <ErrorRetry v-if="loadError" @retry="load" />

    <template v-else>
      <CustomerMoneyHeader :name="customerName" :total="total" :count="invoices.length" />

      <CollectBar
        :show-bar="canBundle && invoices.length > 1"
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
