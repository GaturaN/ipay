<script setup>
import { computed, ref, watch } from 'vue'
import { recordCheque } from '@/data/collection'
import { formatKES } from '@/utils/format'
import BaseDialog from '@/components/BaseDialog.vue'

const MAX_DIMENSION = 1600 // a phone photo is 3-8 MB; the cheque only has to be readable
const JPEG_QUALITY = 0.8
const NUMBER_MAX = 30
const SAVE_TIMEOUT_MS = 30000 // a stalled request must not trap the dialog, since close is blocked while saving

// `target` is { customer, customer_name, invoices: [{name, amount}], outstanding } or null. An
// empty `invoices` records the cheque on account, against no invoice.
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

const invoices = computed(() => props.target?.invoices || [])
const onAccount = computed(() => invoices.value.length === 0)
// Nothing ticked means "attach nothing", never "the whole balance" — the confirm screen spells
// this out, so the wording here stays neutral about what it settles.
const covers = computed(() =>
  onAccount.value
    ? 'On account'
    : `${invoices.value.length} invoice${invoices.value.length === 1 ? '' : 's'} selected`,
)
const settles = computed(() =>
  onAccount.value ? 'No invoice' : `${invoices.value.length} invoice${invoices.value.length === 1 ? '' : 's'}`,
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
  const names = (target.invoices || []).map((inv) => inv.name)
  saving.value = true
  error.value = ''
  try {
    const record = recordCheque({
      customer: target.customer,
      amount: amountValue.value,
      chequeNo: number.value.trim(),
      photo: photo.value,
      invoices: names,
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
    emit('recorded', { invoices: names, amount: amountValue.value, covered: res?.covered || {} })
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
  <BaseDialog :open="Boolean(target)" labelledby="cheque-title" focus="panel" @close="onClose">
    <!-- Recorded: the app's success screen, reworded — it says recorded, never paid. -->
    <template v-if="done">
      <div class="mx-auto grid h-14 w-14 place-items-center rounded-full bg-landed/15 text-2xl text-landed">
        ✓
      </div>
      <h2 id="cheque-title" class="mt-3 text-center font-display text-lg font-bold text-ink">
        Cheque recorded
      </h2>
      <p class="text-center text-sm text-ink/60">Sent to accounts to bank and submit</p>
      <p class="mt-2 text-center font-mono text-3xl font-semibold tabular-nums text-landed">
        {{ formatKES(amountValue) }}
      </p>
      <p class="mt-1 text-center text-sm text-ink/60">
        Cheque {{ number }} · {{ target?.customer_name }}
      </p>
      <button
        type="button"
        class="mt-5 h-12 w-full rounded-xl bg-ink font-semibold text-white"
        @click="$emit('close')"
      >
        Done
      </button>
    </template>

    <!-- Confirm: the only irreversible step, and it reads differently for each mode. -->
    <template v-else-if="reviewing">
      <p class="text-[11px] font-bold uppercase tracking-wider text-ink/50">Confirm</p>
      <h2 id="cheque-title" class="mt-0.5 truncate font-display text-lg font-bold text-ink">
        {{ target?.customer_name }}
      </h2>
      <p class="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink">{{ formatKES(amountValue) }}</p>

      <dl class="mt-4 rounded-xl bg-white px-3">
        <div class="flex justify-between gap-3 border-b border-hairline py-2.5 text-sm">
          <dt class="text-ink/60">Cheque number</dt>
          <dd class="font-mono font-semibold text-ink">{{ number }}</dd>
        </div>
        <div class="flex justify-between gap-3 border-b border-hairline py-2.5 text-sm">
          <dt class="text-ink/60">Banked to</dt>
          <dd class="font-medium text-ink">Undeposited Cheque</dd>
        </div>
        <div class="flex justify-between gap-3 py-2.5 text-sm">
          <dt class="text-ink/60">Settles</dt>
          <dd class="font-medium text-ink">{{ settles }}</dd>
        </div>
      </dl>

      <div v-if="!onAccount" class="mt-2 rounded-xl bg-white px-3">
        <div
          v-for="inv in invoices"
          :key="inv.name"
          class="flex justify-between gap-3 border-b border-hairline py-2 text-sm last:border-0"
        >
          <span class="truncate font-mono text-ink/70">{{ inv.name }}</span>
          <span class="shrink-0 font-mono font-semibold tabular-nums text-ink">{{ formatKES(inv.amount) }}</span>
        </div>
      </div>

      <p v-if="onAccount" class="mt-3 rounded-xl bg-ink/5 px-3 py-2.5 text-xs text-ink/70">
        Recorded against the customer only. Accounts will decide which invoices it settles.
      </p>
      <p class="mt-2 rounded-xl bg-owed/10 px-3 py-2.5 text-xs font-medium text-owed">
        {{
          onAccount
            ? 'Saved as a draft. Nothing is marked paid until accounts submits it.'
            : 'Saved as a draft. These invoices stay outstanding until accounts submits it.'
        }}
      </p>

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
          {{ saving ? 'Saving…' : 'Save for accounts' }}
        </button>
      </div>
    </template>

    <!-- Capture: photo, amount and number on one screen — no branching or server call between. -->
    <template v-else>
      <p class="text-[11px] font-bold uppercase tracking-wider text-ink/50">Cheque collection</p>
      <h2 id="cheque-title" class="mt-0.5 truncate font-display text-lg font-bold text-ink">
        {{ target?.customer_name }}
      </h2>
      <p class="mt-0.5 truncate text-sm text-ink/60">
        {{ covers }}<template v-if="target?.outstanding"> · {{ formatKES(target.outstanding) }}</template>
      </p>

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
        Cheque amount
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
      <p v-if="amountValue > 0" class="mt-1 font-mono text-xs tabular-nums text-ink/50">
        {{ formatKES(amountValue) }}
      </p>
      <p v-else-if="target?.outstanding" class="mt-1 text-xs text-ink/50">
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
          Close
        </button>
        <button
          type="button"
          class="h-12 flex-1 rounded-xl bg-ink font-semibold text-white disabled:opacity-40"
          :disabled="!canReview"
          @click="reviewing = true"
        >
          Continue
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
