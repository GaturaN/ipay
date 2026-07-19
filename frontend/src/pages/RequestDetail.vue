<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  discardBundle,
  fetchRequestDetail,
  getPaymentLink,
  paymentState,
  regeneratePaymentLink,
  startRequestCheckout,
} from '@/data/collection'
import { formatKES } from '@/utils/format'
import PromptDialog from '@/components/PromptDialog.vue'
import ChequeDialog from '@/components/ChequeDialog.vue'
import ErrorRetry from '@/components/ErrorRetry.vue'

// The transient home for a request or bundle: live status, the invoices it
// covers, prompt the full amount, and share/regenerate the link. An unpaid bundle
// the operator backs out of is discarded so its invoices return to the collection
// list — we don't keep "open bundles" lying around.
const route = useRoute()
const router = useRouter()
const name = route.params.name

const detail = ref(null)
const loading = ref(true)
const loadError = ref(false)
const link = ref(null)
const linkBusy = ref(false)
const checkoutBusy = ref(false)
const copied = ref(false)
const linkExpiry = ref(null)
const prompting = ref(null)
const chequing = ref(null)
let pollTimer = null

const SETTLED = ['Success', 'Underpaid', 'Overpaid', 'Cancelled']
// A cheque already collected here makes the request unchargeable (the server refuses every rail),
// so it drops out of promptable exactly like a settled one.
const promptable = computed(
  () => detail.value && !SETTLED.includes(detail.value.status) && !detail.value.awaiting_cheque,
)

// M-Pesa can't process a charge over the ceiling — hide the prompt, steer to the link/iPay.
const mpesaBlocked = computed(
  () => detail.value && detail.value.mpesa_max > 0 && Number(detail.value.amount || 0) > detail.value.mpesa_max,
)

const statusPill = computed(() => {
  const s = detail.value?.status
  if (s === 'Success') return 'bg-landed text-white'
  if (s === 'Underpaid' || s === 'Overpaid') return 'bg-owed text-white'
  if (s === 'Failed' || s === 'Abandoned' || s === 'Cancelled') return 'bg-danger text-white'
  return 'bg-paper/20 text-paper'
})

async function load() {
  loading.value = true
  loadError.value = false
  try {
    detail.value = await fetchRequestDetail(name)
    if (promptable.value) startPolling()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    try {
      const state = await paymentState(name)
      if (state.status && detail.value) detail.value.status = state.status
      if (state.paid || state.partial || state.failed) {
        if (detail.value) detail.value.paid = state.paid
        stopPolling()
      }
    } catch {
      // Transient — keep polling.
    }
  }, 4000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}
onUnmounted(stopPolling)

// One poller at a time: pause the page poll while the prompt dialog (which polls
// too) is open.
watch(prompting, (target) => {
  if (target) stopPolling()
  else if (promptable.value) startPolling()
})

function promptNow() {
  prompting.value = {
    name: detail.value.name,
    title: detail.value.customer_name,
    subtitle: detail.value.is_bundle ? 'Bundle' : '',
    phone: detail.value.customer_phone,
    amount: Number(detail.value.amount || 0),
    kind: 'request',
  }
}

function onPaid() {
  if (detail.value) {
    detail.value.status = 'Success'
    detail.value.paid = true
  }
  stopPolling()
  prompting.value = null // dismiss the success screen
}

function chequeNow() {
  chequing.value = {
    customer: detail.value.customer,
    customer_name: detail.value.customer_name,
    invoices: detail.value.invoices.map((inv) => ({ name: inv.name, amount: Number(inv.amount || 0) })),
    outstanding: Number(detail.value.amount || 0),
  }
}

// A cheque covers the request's invoices, so the whole request is now awaiting one — mark it so
// the charge actions give way to the notice, without a reload.
function onChequeRecorded({ covered }) {
  const total = Object.values(covered || {}).reduce((sum, v) => sum + Number(v || 0), 0)
  if (detail.value) detail.value.awaiting_cheque = total
  stopPolling()
}

async function payViaIpay() {
  checkoutBusy.value = true
  try {
    const res = await startRequestCheckout(name)
    if (res?.url) window.location = res.url
  } finally {
    checkoutBusy.value = false
  }
}

async function showLink() {
  linkBusy.value = true
  try {
    const res = await getPaymentLink(name)
    link.value = res.url
    linkExpiry.value = res.expiry || null
    copied.value = false
  } finally {
    linkBusy.value = false
  }
}

async function regenerate() {
  linkBusy.value = true
  try {
    const res = await regeneratePaymentLink(name)
    link.value = res.url
    linkExpiry.value = res.expiry || null
    copied.value = false
  } finally {
    linkBusy.value = false
  }
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(link.value)
    copied.value = true
  } catch {
    // Clipboard unavailable — the link stays selectable above.
  }
}

// Discard an unpaid bundle on leave so its invoices return to the collection
// list. discardBundle is a safe no-op server-side for a single or paid request,
// so we call it on every leave (and don't depend on `detail` having loaded yet).
// Guarded so the explicit Back and the route-leave guard don't both run it.
let discarded = false
let discarding = false
async function discardIfNeeded() {
  if (discarded || discarding) return
  discarding = true
  try {
    await discardBundle(name)
    discarded = true // latch only on success, so a failed call can retry on the next leave
  } catch {
    // Best-effort; a paid bundle is kept by the server, and the 30-min stale
    // window returns the invoices even if every discard attempt fails.
  } finally {
    discarding = false
  }
}

// Discard BEFORE navigating so the Collect list reloads after the bundle is
// cancelled (not before) — otherwise its invoices look lost.
async function backToList() {
  await discardIfNeeded()
  // Return to where the bundle was started: the customer it was built from (internal or
  // field, preserving that page's scope), else the top list.
  const q = route.query
  if (q.from === 'sales') {
    router.push(
      q.customer
        ? {
            name: 'SalesCustomer',
            params: { customer: q.customer },
            query: { ...(q.payment_term ? { payment_term: q.payment_term } : {}) },
          }
        : { name: 'Sales' },
    )
  } else if (q.from === 'internal') {
    router.push(
      q.customer
        ? {
            name: 'InternalCustomer',
            params: { customer: q.customer },
            query: {
              ...(q.driver ? { driver: q.driver } : {}),
              ...(q.payment_term ? { payment_term: q.payment_term } : {}),
              ...(q.sales_person ? { sales_person: q.sales_person } : {}),
            },
          }
        : { name: 'Internal' },
    )
  } else if (q.from === 'field' && q.customer) {
    router.push({
      name: 'Customer',
      params: { customer: q.customer },
      query: q.driver ? { driver: q.driver } : {},
    })
  } else {
    router.push({ name: 'Collect' })
  }
}

// Fallback for browser-back / any other navigation away.
onBeforeRouteLeave(discardIfNeeded)

onMounted(load)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-md flex-col gap-4 p-4">
    <button class="self-start text-sm font-medium text-ink/70" @click="backToList">‹ Back</button>

    <p v-if="loading" class="py-10 text-center text-sm text-ink/50">Loading…</p>

    <ErrorRetry v-else-if="loadError" @retry="load" />

    <template v-else-if="detail">
      <section class="rounded-2xl bg-ink px-5 py-4 text-paper">
        <p class="truncate font-display text-lg font-bold">{{ detail.customer_name }}</p>
        <p class="mt-1 font-mono text-3xl font-semibold tabular-nums">{{ formatKES(detail.amount) }}</p>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <span class="rounded-full px-2.5 py-0.5 text-xs font-semibold" :class="statusPill">
            {{ detail.status }}
          </span>
          <span class="font-mono text-xs text-paper/50">
            {{ detail.name }} · {{ detail.is_bundle ? 'Bundle' : 'Single' }}
          </span>
        </div>
      </section>

      <p v-if="detail.result_detail" class="rounded-xl bg-paper px-3 py-2 text-xs text-ink/70">
        {{ detail.result_detail }}
      </p>

      <div class="rounded-2xl border border-hairline bg-white p-4">
        <p class="font-display text-sm font-semibold text-ink">
          {{ detail.is_bundle ? `Invoices (${detail.invoices.length})` : 'Invoice' }}
        </p>
        <ul class="mt-1 divide-y divide-hairline">
          <li
            v-for="inv in detail.invoices"
            :key="inv.name"
            class="flex items-center justify-between gap-3 py-2"
          >
            <span class="truncate font-mono text-sm text-ink/80">{{ inv.name }}</span>
            <span class="shrink-0 font-mono text-sm font-semibold tabular-nums text-ink">
              {{ formatKES(inv.amount) }}
            </span>
          </li>
        </ul>
      </div>

      <template v-if="promptable">
        <button
          v-if="!mpesaBlocked"
          type="button"
          class="h-14 rounded-xl bg-mpesa text-lg font-semibold text-white transition active:scale-[.98]"
          @click="promptNow"
        >
          Prompt M-Pesa — {{ formatKES(detail.amount) }}
        </button>
        <p v-else class="rounded-xl bg-owed/10 px-3 py-2 text-sm text-owed">
          M-Pesa isn't available for amounts over {{ formatKES(detail.mpesa_max) }}.
          {{
            detail.enable_redirect
              ? 'Use Pay via iPay below, or share the payment link.'
              : 'Card checkout is off — please contact the internal team.'
          }}
        </p>

        <button
          v-if="detail.enable_redirect"
          type="button"
          class="h-14 rounded-xl border-2 border-mpesa text-lg font-semibold text-mpesa transition active:scale-[.98] disabled:opacity-50"
          :disabled="checkoutBusy"
          :aria-busy="checkoutBusy"
          @click="payViaIpay"
        >
          {{ checkoutBusy ? 'Opening…' : `Pay via iPay — ${formatKES(detail.amount)}` }}
        </button>

        <div v-if="detail.enable_redirect" class="rounded-2xl border border-hairline bg-white p-4">
          <div class="flex gap-2">
            <button
              type="button"
              class="h-11 flex-1 rounded-xl border border-hairline font-medium text-ink disabled:opacity-50"
              :disabled="linkBusy"
              :aria-busy="linkBusy"
              @click="showLink"
            >
              {{ linkBusy ? 'Loading…' : 'Payment link' }}
            </button>
            <button
              type="button"
              class="h-11 flex-1 rounded-xl border border-hairline font-medium text-ink disabled:opacity-50"
              :disabled="linkBusy"
              :aria-busy="linkBusy"
              @click="regenerate"
            >
              Regenerate
            </button>
          </div>
          <div v-if="link" class="mt-3">
            <div class="break-all rounded-lg border border-hairline bg-paper p-2 text-xs text-ink/80">
              {{ link }}
            </div>
            <button
              type="button"
              class="mt-2 h-11 w-full rounded-xl bg-ink font-medium text-paper"
              @click="copyLink"
            >
              {{ copied ? 'Copied ✓' : 'Copy link' }}
            </button>
          </div>
        </div>

        <!-- Deliberately quiet: cheques are the exception, M-Pesa stays the obvious action. -->
        <button
          v-if="detail.allow_cheque"
          type="button"
          class="h-11 rounded-xl border border-hairline bg-white text-sm font-medium text-ink/70 transition active:bg-paper"
          @click="chequeNow"
        >
          Collect a cheque
        </button>
      </template>

      <p
        v-else-if="detail.awaiting_cheque"
        class="rounded-xl bg-owed/10 px-3 py-2.5 text-sm font-medium text-owed"
      >
        Cheque for {{ formatKES(detail.awaiting_cheque) }} collected — with accounts to bank. This
        request can't be charged until it clears.
      </p>

      <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" />
      <ChequeDialog :target="chequing" @close="chequing = null" @recorded="onChequeRecorded" />
    </template>
  </main>
</template>
