<script setup>
import { computed, ref, watch } from 'vue'
import { recordCheque } from '@/data/collection'
import { formatKES } from '@/utils/format'
import BaseDialog from '@/components/BaseDialog.vue'

const MAX_DIMENSION = 1600 // a phone photo is 3-8 MB; the cheque only has to be readable
const JPEG_QUALITY = 0.8
const NUMBER_MAX = 30
const SAVE_TIMEOUT_MS = 30000 // a stalled request must not trap the dialog, since close is blocked while saving

// `target` is { customer, customer_name, invoices, outstanding } or null. An empty `invoices`
// records the cheque on account, against no invoice.
const props = defineProps({ target: { type: Object, default: null } })
const emit = defineEmits(['close', 'recorded'])

const photo = ref('') // downscaled data URL, exactly what the server stores
const fileInput = ref(null)
const amount = ref('')
const number = ref('')
const reviewing = ref(false)
const saving = ref(false)
const done = ref(false)
const error = ref('')

const invoiceCount = computed(() => props.target?.invoices?.length || 0)
const covers = computed(() =>
  invoiceCount.value
    ? `${invoiceCount.value} invoice${invoiceCount.value === 1 ? '' : 's'}`
    : 'On account',
)
const amountValue = computed(() => Number(amount.value) || 0)
const canReview = computed(() => Boolean(photo.value) && amountValue.value > 0 && Boolean(number.value.trim()))

// Shrink in the browser: a full-size photo would blow the upload cap and a slow line.
function downscale(file) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onerror = () => reject(new Error('unreadable'))
    image.onload = () => {
      const scale = Math.min(1, MAX_DIMENSION / Math.max(image.width, image.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(image.width * scale)
      canvas.height = Math.round(image.height * scale)
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height)
      resolve(canvas.toDataURL('image/jpeg', JPEG_QUALITY))
      URL.revokeObjectURL(image.src)
    }
    image.src = URL.createObjectURL(file)
  })
}

function pickPhoto() {
  fileInput.value?.click()
}

function clearFileInput() {
  // Reset the input so choosing the same file again still fires change.
  if (fileInput.value) fileInput.value.value = ''
}

function removePhoto() {
  photo.value = ''
  error.value = ''
  clearFileInput()
}

async function onPick(event) {
  const file = event.target.files?.[0]
  clearFileInput()
  if (!file) return
  error.value = ''
  try {
    photo.value = await downscale(file)
  } catch {
    error.value = "That photo couldn't be read. Try again."
  }
}

// A record in flight must never be abandoned: closing here would strand the cheque with no
// marker and the driver would re-prompt for money already collected.
function onClose() {
  if (saving.value) return
  emit('close')
}

async function save() {
  if (saving.value) return
  // Capture the target before awaiting: it is what we record and emit, and it must not change
  // under us if the dialog is reopened for another invoice mid-save.
  const target = props.target
  saving.value = true
  error.value = ''
  try {
    const record = recordCheque({
      customer: target.customer,
      amount: amountValue.value,
      chequeNo: number.value.trim(),
      photo: photo.value,
      invoices: target.invoices || [],
    })
    // Bound the wait: a hung request would otherwise leave saving true forever, and close is
    // blocked while saving. On timeout we cannot know the outcome, so tell them to check first.
    const res = await Promise.race([
      record,
      new Promise((_, reject) => setTimeout(() => reject({ timedOut: true }), SAVE_TIMEOUT_MS)),
    ])
    done.value = true
    // covered maps each invoice to the amount this cheque put against it, so the card shows the
    // real figure rather than a placeholder.
    emit('recorded', {
      invoices: target.invoices || [],
      amount: amountValue.value,
      covered: res?.covered || {},
    })
  } catch (e) {
    error.value = e?.timedOut
      ? 'That took too long. Check the invoice before recording it again.'
      : e?.messages?.[0] || "Couldn't record the cheque."
    reviewing.value = false // back to the form, with everything they typed still there
  } finally {
    saving.value = false
  }
}

watch(
  () => props.target,
  () => {
    photo.value = ''
    clearFileInput()
    amount.value = ''
    number.value = ''
    reviewing.value = false
    saving.value = false
    done.value = false
    error.value = ''
  },
)
</script>

<template>
  <BaseDialog
    :open="Boolean(target)"
    labelledby="cheque-title"
    focus="panel"
    @close="onClose"
  >
    <h2 id="cheque-title" class="font-display text-lg font-bold text-ink">
      {{ done ? 'Cheque recorded' : reviewing ? 'Check this is right' : 'Collect a cheque' }}
    </h2>
    <p class="mt-0.5 truncate text-sm text-ink/60">{{ target?.customer_name }} · {{ covers }}</p>

    <!-- Recorded: say plainly that no money has moved yet, so nobody treats it as paid. -->
    <template v-if="done">
      <p class="mt-4 rounded-xl bg-paper p-4 text-sm text-ink/80">
        {{ formatKES(amountValue) }} — cheque {{ number }}. Accounts will bank it and confirm the
        payment. The invoice stays open until it clears.
      </p>
      <button
        type="button"
        class="mt-4 h-12 w-full rounded-xl bg-ink font-semibold text-white"
        @click="$emit('close')"
      >
        Done
      </button>
    </template>

    <template v-else-if="reviewing">
      <img :src="photo" alt="The cheque photo" class="mt-4 max-h-40 w-full rounded-xl object-contain" />
      <dl class="mt-3 divide-y divide-hairline rounded-xl bg-paper px-3">
        <div class="flex justify-between gap-3 py-2.5">
          <dt class="text-sm text-ink/60">Amount</dt>
          <dd class="font-mono text-base font-semibold tabular-nums text-ink">
            {{ formatKES(amountValue) }}
          </dd>
        </div>
        <div class="flex justify-between gap-3 py-2.5">
          <dt class="text-sm text-ink/60">Cheque number</dt>
          <dd class="font-mono text-sm font-semibold text-ink">{{ number }}</dd>
        </div>
        <div class="flex justify-between gap-3 py-2.5">
          <dt class="text-sm text-ink/60">Covers</dt>
          <dd class="text-sm font-medium text-ink">{{ covers }}</dd>
        </div>
      </dl>
      <p v-if="error" class="mt-2 text-sm text-danger">{{ error }}</p>
      <div class="mt-4 flex gap-2">
        <button
          type="button"
          class="h-12 shrink-0 rounded-xl border border-hairline px-5 font-medium text-ink"
          :disabled="saving"
          @click="reviewing = false"
        >
          Back
        </button>
        <!-- Never bg-mpesa: green is the M-Pesa rail, and no money moves here. -->
        <button
          type="button"
          class="h-12 flex-1 rounded-xl bg-ink font-semibold text-white disabled:opacity-40"
          :disabled="saving"
          :aria-busy="saving"
          @click="save"
        >
          {{ saving ? 'Recording…' : 'Record cheque' }}
        </button>
      </div>
    </template>

    <template v-else>
      <button
        v-if="!photo"
        type="button"
        class="mt-4 grid h-32 w-full place-items-center rounded-xl border border-dashed border-hairline bg-paper text-sm font-medium text-ink/60"
        @click="pickPhoto"
      >
        <span class="flex flex-col items-center gap-1">
          <svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 8.5h4L8.5 6h7L17 8.5h4v10H3z" stroke-linejoin="round" />
            <circle cx="12" cy="13" r="3.2" />
          </svg>
          Photograph the cheque
        </span>
      </button>
      <div v-else class="mt-4">
        <img :src="photo" alt="The cheque photo" class="h-32 w-full rounded-xl border border-hairline bg-paper object-contain" />
        <div class="mt-2 flex gap-2">
          <button
            type="button"
            class="h-10 flex-1 rounded-xl border border-hairline text-sm font-medium text-ink"
            @click="pickPhoto"
          >
            Retake
          </button>
          <button
            type="button"
            class="h-10 flex-1 rounded-xl border border-hairline text-sm font-medium text-danger"
            @click="removePhoto"
          >
            Remove
          </button>
        </div>
      </div>
      <input ref="fileInput" type="file" accept="image/*" capture="environment" class="sr-only" @change="onPick" />

      <label class="mt-3 block text-xs font-semibold text-ink/60" for="cheque-amount">
        Amount on the cheque
      </label>
      <input
        id="cheque-amount"
        v-model="amount"
        type="number"
        inputmode="decimal"
        min="0"
        placeholder="0"
        class="mt-1 h-12 w-full rounded-xl border border-hairline bg-white px-3 font-mono text-base tabular-nums text-ink focus:border-ink focus:outline-none focus:ring-2 focus:ring-ink/20"
      />
      <p v-if="target?.outstanding" class="mt-1 text-xs text-ink/50">
        Outstanding {{ formatKES(target.outstanding) }} — enter what the cheque says.
      </p>

      <label class="mt-3 block text-xs font-semibold text-ink/60" for="cheque-number">
        Cheque number
      </label>
      <input
        id="cheque-number"
        v-model="number"
        type="text"
        inputmode="numeric"
        :maxlength="NUMBER_MAX"
        placeholder="001894"
        class="mt-1 h-12 w-full rounded-xl border border-hairline bg-white px-3 font-mono text-base text-ink focus:border-ink focus:outline-none focus:ring-2 focus:ring-ink/20"
      />

      <p v-if="error" class="mt-2 text-sm text-danger">{{ error }}</p>

      <div class="mt-4 flex gap-2">
        <button
          type="button"
          class="h-12 shrink-0 rounded-xl border border-hairline px-5 font-medium text-ink"
          @click="$emit('close')"
        >
          Cancel
        </button>
        <button
          type="button"
          class="h-12 flex-1 rounded-xl bg-ink font-semibold text-white disabled:opacity-40"
          :disabled="!canReview"
          @click="reviewing = true"
        >
          Review
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
