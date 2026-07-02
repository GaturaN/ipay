<script setup>
defineEmits(['retry'])
</script>

<template>
  <div class="py-16 text-center">
    <p class="font-display text-ink/70">Couldn't load — check your connection.</p>
    <button
      type="button"
      class="mt-3 h-11 rounded-xl bg-mpesa px-5 font-semibold text-white"
      @click="$emit('retry')"
    >
      Retry
    </button>
  </div>
</template>
