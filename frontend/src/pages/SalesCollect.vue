<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchSalesCustomers } from '@/data/collection'
import { useResumeRefresh } from '@/composables/useResumeRefresh'
import { formatKES } from '@/utils/format'
import CustomerListShell from '@/components/CustomerListShell.vue'

const route = useRoute()

// Sales mode: a member's OWN book — every customer their Sales Person is named on, across
// all payment terms (they chase receivables, not just collect-on-delivery). A manager sees
// every member's book and filters to one, like an operator does with drivers. The server
// resolves a member from the login, so nothing here can widen a member's scope.
const customers = ref([])
const listLoading = ref(true)
const loadError = ref(false)
const notPermitted = ref(false)
const unmapped = ref(false) // login has no Sales Person — the page explains rather than looking empty
const isManager = ref(false)
const person = ref('') // the member whose book is shown; blank = every book (manager)

const search = ref('')
const paymentTerms = ref([])
const paymentTerm = ref(route.query.payment_term || '')
const salesPersons = ref([])
const salesPerson = ref(route.query.sales_person || '')

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return customers.value
  return customers.value.filter((c) => c.customer_name.toLowerCase().includes(query))
})

const bookTotal = computed(() =>
  filtered.value.reduce((sum, c) => sum + Number(c.total_outstanding || 0), 0),
)

const emptyMessage = computed(() => {
  if (unmapped.value)
    return 'Your login is not linked to a sales person yet. Ask an administrator to set the User on your Employee record.'
  if (search.value.trim()) return 'No customers match your search.'
  return 'None of your customers have an outstanding balance.'
})

async function loadCustomers() {
  listLoading.value = true
  loadError.value = false
  notPermitted.value = false
  try {
    const data = await fetchSalesCustomers(paymentTerm.value, salesPerson.value)
    customers.value = data.customers || []
    paymentTerms.value = data.payment_terms || []
    salesPersons.value = data.sales_persons || []
    person.value = data.sales_person || ''
    isManager.value = Boolean(data.is_manager)
    unmapped.value = Boolean(data.unmapped)
  } catch (e) {
    if (e?.exc_type === 'PermissionError' || e?.response?.status === 403) notPermitted.value = true
    else loadError.value = true
  } finally {
    listLoading.value = false
  }
}

useResumeRefresh(loadCustomers) // re-pull when the PWA returns to the foreground
onMounted(loadCustomers)
</script>

<template>
  <CustomerListShell
    container-class="max-w-5xl"
    title="My Collections"
    :list-loading="listLoading"
    :load-error="loadError"
    :not-permitted="notPermitted"
    :customers="filtered"
    :empty-message="emptyMessage"
    card-route-name="SalesCustomer"
    :card-payment-term="paymentTerm"
    :card-sales-person="salesPerson"
    @retry="loadCustomers"
  >
    <template #header>
      <section class="rounded-2xl bg-ink px-5 py-4 text-paper">
        <p class="font-display text-xs font-semibold uppercase tracking-widest text-paper/60">
          {{ person || (isManager ? 'All sales members' : 'My book') }}
        </p>
        <p class="mt-1 font-mono text-3xl font-semibold tabular-nums">
          {{ listLoading ? '—' : formatKES(bookTotal) }}
        </p>
        <p class="text-sm text-paper/60">
          outstanding across {{ filtered.length }} customer{{ filtered.length === 1 ? '' : 's' }}
        </p>
      </section>
    </template>

    <template #filters>
      <input
        v-model="search"
        type="search"
        aria-label="Search customers"
        placeholder="Search customer…"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-4 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:max-w-sm"
      />
      <select
        v-if="paymentTerms.length"
        v-model="paymentTerm"
        aria-label="Filter by payment term"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-3 text-sm text-ink focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:w-48"
        @change="loadCustomers"
      >
        <option value="">All terms</option>
        <option v-for="t in paymentTerms" :key="t" :value="t">{{ t }}</option>
      </select>
      <!-- Managers only: a member's own book is already locked to them server-side. -->
      <select
        v-if="salesPersons.length"
        v-model="salesPerson"
        aria-label="Filter by sales team member"
        class="h-11 w-full rounded-xl border border-hairline bg-white px-3 text-sm text-ink focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40 sm:w-48"
        @change="loadCustomers"
      >
        <option value="">All sales members</option>
        <option v-for="p in salesPersons" :key="p" :value="p">{{ p }}</option>
      </select>
    </template>
  </CustomerListShell>
</template>
