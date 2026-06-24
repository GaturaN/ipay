<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  fetchRequestDetail,
  getPaymentLink,
  paymentState,
  regeneratePaymentLink,
  splitBundle,
} from '@/data/collection'
import { formatKES } from '@/utils/format'
import PromptDialog from '@/components/PromptDialog.vue'

// The home for a single request or a bundle: live status, the invoices it
// covers, prompt the full amount, share/regenerate the link, and split a bundle.
const route = useRoute()
const router = useRouter()
const name = route.params.name

const detail = ref(null)
const loading = ref(true)
const link = ref(null)
const linkBusy = ref(false)
const copied = ref(false)
const splitBusy = ref(false)
const prompting = ref(null)
let pollTimer = null

const statusTone = computed(() => {
  const s = detail.value?.status
  if (s === 'Success') return 'text-green-700'
  if (s === 'Underpaid' || s === 'Overpaid') return 'text-amber-700'
  if (s === 'Failed' || s === 'Abandoned') return 'text-red-700'
  return 'text-gray-500'
})

async function load() {
  loading.value = true
  try {
    detail.value = await fetchRequestDetail(name)
    if (!detail.value.paid) startPolling()
  } finally {
    loading.value = false
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    try {
      const state = await paymentState(name)
      if (state.status && detail.value) detail.value.status = state.status
      if (state.paid || state.partial || state.failed) {
        detail.value.paid = state.paid
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

function promptNow() {
  prompting.value = {
    name: detail.value.name,
    label: `${detail.value.customer_name} · ${formatKES(detail.value.amount)}`,
    phone: detail.value.customer_phone,
    kind: 'request',
  }
}

function onPaid() {
  detail.value.status = 'Success'
  detail.value.paid = true
  stopPolling()
}

async function showLink() {
  linkBusy.value = true
  try {
    link.value = (await getPaymentLink(name)).url
    copied.value = false
  } finally {
    linkBusy.value = false
  }
}

async function regenerate() {
  linkBusy.value = true
  try {
    link.value = (await regeneratePaymentLink(name)).url
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

async function doSplit() {
  if (!window.confirm('Split this bundle into individual requests and cancel it?')) return
  splitBusy.value = true
  try {
    await splitBundle(name)
    router.replace('/') // the individual invoices reappear on the collection list
  } finally {
    splitBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="mx-auto flex min-h-full w-full max-w-md flex-col gap-4 p-4">
    <button class="self-start text-sm text-gray-500" @click="router.back()">← Back</button>

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

      <Button v-if="!detail.paid" variant="solid" theme="green" @click="promptNow">
        Prompt M-Pesa (full amount)
      </Button>

      <div class="rounded-xl border border-gray-200 bg-white p-4">
        <div class="flex gap-2">
          <Button class="flex-1" :loading="linkBusy" @click="showLink">Payment link</Button>
          <Button v-if="!detail.paid" class="flex-1" :loading="linkBusy" @click="regenerate">
            Regenerate
          </Button>
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

      <Button v-if="detail.can_split" variant="ghost" :loading="splitBusy" @click="doSplit">
        Split into individual requests
      </Button>

      <PromptDialog :target="prompting" @close="prompting = null" @paid="onPaid" />
    </template>
  </main>
</template>
