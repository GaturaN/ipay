<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  discardBundle,
  fetchRequestDetail,
  getPaymentLink,
  paymentState,
  regeneratePaymentLink,
} from '@/data/collection'
import { formatKES } from '@/utils/format'
import PromptDialog from '@/components/PromptDialog.vue'

// The transient home for a request or bundle: live status, the invoices it
// covers, prompt the full amount, and share/regenerate the link. An unpaid bundle
// the operator backs out of is discarded so its invoices return to the collection
// list — we don't keep "open bundles" lying around.
const route = useRoute()
const router = useRouter()
const name = route.params.name

const detail = ref(null)
const loading = ref(true)
const link = ref(null)
const linkBusy = ref(false)
const copied = ref(false)
const linkExpiry = ref(null)
const prompting = ref(null)
let pollTimer = null

const SETTLED = ['Success', 'Underpaid', 'Overpaid', 'Cancelled']
const promptable = computed(() => detail.value && !SETTLED.includes(detail.value.status))

const statusTone = computed(() => {
  const s = detail.value?.status
  if (s === 'Success') return 'text-green-700'
  if (s === 'Underpaid' || s === 'Overpaid') return 'text-amber-700'
  if (s === 'Failed' || s === 'Abandoned' || s === 'Cancelled') return 'text-red-700'
  return 'text-gray-500'
})

async function load() {
  loading.value = true
  try {
    detail.value = await fetchRequestDetail(name)
    if (promptable.value) startPolling()
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
    label: `${detail.value.customer_name} · ${formatKES(detail.value.amount)}`,
    phone: detail.value.customer_phone,
    kind: 'request',
  }
}

function onPaid() {
  if (detail.value) {
    detail.value.status = 'Success'
    detail.value.paid = true
  }
  stopPolling()
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
  router.push({ name: 'Collect' })
}

// Fallback for browser-back / any other navigation away.
onBeforeRouteLeave(discardIfNeeded)

onMounted(load)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-md flex-col gap-4 p-4">
    <button class="self-start text-sm text-gray-500" @click="backToList">← Back</button>

    <p v-if="loading" class="py-10 text-center text-sm text-gray-400">Loading…</p>

    <template v-else-if="detail">
      <header>
        <h1 class="text-xl font-semibold text-gray-900">{{ detail.customer_name }}</h1>
        <p class="text-sm text-gray-500">
          {{ detail.name }} · {{ detail.is_bundle ? 'Bundle' : 'Single' }}
        </p>
      </header>

      <div class="rounded-xl border border-gray-200 bg-white p-4">
        <div class="flex items-baseline justify-between">
          <span class="text-sm text-gray-500">Amount</span>
          <span class="text-lg font-semibold tabular-nums">{{ formatKES(detail.amount) }}</span>
        </div>
        <div class="mt-1 flex items-baseline justify-between">
          <span class="text-sm text-gray-500">Status</span>
          <span class="font-medium" :class="statusTone">{{ detail.status }}</span>
        </div>
        <p v-if="detail.result_detail" class="mt-2 text-xs text-gray-500">
          {{ detail.result_detail }}
        </p>
      </div>

      <div class="rounded-xl border border-gray-200 bg-white p-4">
        <p class="text-sm font-medium text-gray-700">Invoices ({{ detail.invoices.length }})</p>
        <ul class="mt-2 space-y-1 text-sm text-gray-600">
          <li v-for="inv in detail.invoices" :key="inv" class="truncate">{{ inv }}</li>
        </ul>
      </div>

      <template v-if="promptable">
        <Button variant="solid" theme="green" @click="promptNow">
          Prompt M-Pesa (full amount)
        </Button>

        <div class="rounded-xl border border-gray-200 bg-white p-4">
          <div class="flex gap-2">
            <Button class="flex-1" :loading="linkBusy" @click="showLink">Payment link</Button>
            <Button class="flex-1" :loading="linkBusy" @click="regenerate">Regenerate</Button>
          </div>
          <div v-if="link" class="mt-3">
            <div class="break-all rounded-lg border border-gray-200 bg-gray-50 p-2 text-xs">
              {{ link }}
            </div>
            <Button variant="subtle" class="mt-2 w-full" @click="copyLink">
              {{ copied ? 'Copied ✓' : 'Copy link' }}
            </Button>
          </div>
        </div>
      </template>

      <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" />
    </template>
  </main>
</template>
