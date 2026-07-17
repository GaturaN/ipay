<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'

// The app's modal shell: backdrop, panel, Escape and a Tab trap. Every dialog is built on this
// so the trap exists once — it was copied by hand before and the copies drifted apart.
const props = defineProps({
  open: Boolean,
  labelledby: { type: String, required: true },
  // Where focus lands on open. 'panel' leaves a phone at the top of the content rather than
  // scrolling to the first field.
  focus: { type: String, default: 'input' },
})
const emit = defineEmits(['close'])

const panel = ref(null)

// Escape and the backdrop both just report intent; the caller decides what closing means.
function onKeydown(e) {
  if (e.key === 'Escape') return emit('close')
  if (e.key !== 'Tab') return
  // The panel leads the list: it holds focus on open, and querySelectorAll sees only its
  // descendants — without it Shift+Tab lands on the page behind.
  const items = [
    panel.value,
    ...Array.from(
      panel.value?.querySelectorAll(
        'textarea, input, select, button, [href], [tabindex]:not([tabindex="-1"])',
      ) || [],
    ),
  ].filter((el) => el && !el.disabled)
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

watch(
  () => props.open,
  (open) => {
    window[open ? 'addEventListener' : 'removeEventListener']('keydown', onKeydown)
    if (open)
      nextTick(() =>
        (props.focus === 'input' ? panel.value?.querySelector('input') : panel.value)?.focus(),
      )
  },
)

onUnmounted(() => window.removeEventListener('keydown', onKeydown))

defineExpose({ panel })
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-end justify-center bg-ink/50 p-4 sm:items-center"
    @click.self="$emit('close')"
  >
    <div
      ref="panel"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="labelledby"
      tabindex="-1"
      class="w-full max-w-md rounded-3xl bg-paper p-6 focus:outline-none"
    >
      <slot />
    </div>
  </div>
</template>
