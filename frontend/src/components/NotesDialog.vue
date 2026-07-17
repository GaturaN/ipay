<script setup>
import { computed, ref, watch } from 'vue'
import { addInvoiceNote, fetchInvoiceNotes } from '@/data/collection'
import { formatDateTime } from '@/utils/format'
import BaseDialog from '@/components/BaseDialog.vue'

const MAX = 500

// `target` is { invoice, customer_name } or null — null closes the dialog.
const props = defineProps({ target: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])

const notes = ref([])
const draft = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
let loadSeq = 0 // guards against out-of-order responses when invoices are opened in quick succession

const canSave = computed(() => Boolean(draft.value.trim()) && !saving.value)

async function load() {
  const seq = ++loadSeq
  const invoice = props.target.invoice
  loading.value = true
  error.value = ''
  try {
    const rows = await fetchInvoiceNotes(invoice)
    if (seq !== loadSeq) return // a newer open superseded this response — drop it
    notes.value = rows
  } catch {
    if (seq === loadSeq) error.value = "Couldn't load the notes."
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function save() {
  if (!canSave.value) return
  const invoice = props.target.invoice
  saving.value = true
  error.value = ''
  try {
    await addInvoiceNote(invoice, draft.value.trim())
    draft.value = ''
    await load()
    // Hand the card its new count/preview rather than making the page refetch: a reload would
    // clear the operator's ticked bundle and reset paging behind this dialog.
    emit('saved', { invoice, count: notes.value.length, latest: notes.value[0]?.content || '' })
  } catch (e) {
    error.value = e?.messages?.[0] || "Couldn't save the note."
  } finally {
    saving.value = false
  }
}

watch(
  () => props.target,
  (target) => {
    draft.value = ''
    error.value = ''
    notes.value = []
    if (target) load()
  },
)
</script>

<template>
  <!-- focus="panel": the operator opened this to READ; don't scroll them past the notes. -->
  <BaseDialog :open="Boolean(target)" labelledby="notes-title" focus="panel" @close="$emit('close')">
    <h2 id="notes-title" class="font-display text-lg font-bold text-ink">Notes</h2>
    <p class="mt-0.5 truncate text-sm text-ink/60">
      {{ target.customer_name }} · {{ target.invoice }}
    </p>

    <p v-if="loading" class="py-6 text-center text-sm text-ink/50">Loading…</p>
    <div v-else-if="notes.length" class="mt-4 flex max-h-56 flex-col gap-2 overflow-y-auto">
      <div v-for="note in notes" :key="note.name" class="rounded-xl bg-white p-3">
        <div class="flex justify-between gap-2 text-[11px] font-semibold text-ink/55">
          <span class="truncate">{{ note.author }}</span>
          <span class="shrink-0">{{ formatDateTime(note.creation) }}</span>
        </div>
        <p class="mt-0.5 whitespace-pre-wrap break-words text-sm text-ink">{{ note.content }}</p>
      </div>
    </div>
    <p v-else class="py-6 text-center text-sm text-ink/50">No notes yet.</p>

    <textarea
      v-model="draft"
      rows="3"
      :maxlength="MAX"
      aria-label="Add a note"
      placeholder="Add a note about collecting this invoice…"
      class="mt-4 w-full rounded-xl border border-hairline bg-white px-3 py-2 text-sm text-ink placeholder:text-ink/50 focus:border-mpesa focus:outline-none focus:ring-2 focus:ring-mpesa/40"
    />
    <p v-if="error" class="mt-2 text-sm text-danger">{{ error }}</p>

    <div class="mt-3 flex items-center justify-between gap-3">
      <span class="font-mono text-[11px] tabular-nums text-ink/50">{{ draft.length }} / {{ MAX }}</span>
      <div class="flex gap-2">
        <button
          type="button"
          class="h-11 rounded-xl border border-hairline bg-white px-4 font-medium text-ink"
          @click="$emit('close')"
        >
          Close
        </button>
        <button
          type="button"
          class="h-11 rounded-xl bg-mpesa px-5 font-semibold text-white disabled:opacity-40"
          :disabled="!canSave"
          :aria-busy="saving"
          @click="save"
        >
          {{ saving ? 'Saving…' : 'Save note' }}
        </button>
      </div>
    </div>
  </BaseDialog>
</template>
