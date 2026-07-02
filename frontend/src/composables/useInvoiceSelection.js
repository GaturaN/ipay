import { computed, ref } from 'vue'

// Shared invoice-selection state for the customer detail pages: tick a subset to bundle
// only those; nothing ticked = collect the whole balance.
export function useInvoiceSelection() {
  const selected = ref([])
  const isSelected = (inv) => selected.value.some((i) => i.name === inv.name)

  function toggleSelect(inv) {
    selected.value = isSelected(inv)
      ? selected.value.filter((i) => i.name !== inv.name)
      : [...selected.value, inv]
  }

  const clearSelection = () => (selected.value = [])
  const dropSelected = (name) => (selected.value = selected.value.filter((i) => i.name !== name))

  const selectedTotal = computed(() =>
    selected.value.reduce((sum, inv) => sum + Number(inv.outstanding_amount || 0), 0),
  )

  return { selected, isSelected, toggleSelect, clearSelection, dropSelected, selectedTotal }
}
