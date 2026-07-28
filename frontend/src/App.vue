<script setup>
import InstallPrompt from './components/InstallPrompt.vue'
</script>

<template>
  <div class="h-full bg-gray-50 text-gray-900">
    <router-view />
    <InstallPrompt />
  </div>
</template>
