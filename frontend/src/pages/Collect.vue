<script setup>
import { computed } from 'vue'
import { useSession } from '@/stores/session'

// Milestone ① placeholder: proves the SPA renders on a phone, frappe-ui is
// wired, and the shared Frappe session is readable. The real collection list
// (search, driver filter, stats, actions) lands in milestone ③.
const session = useSession()
const greeting = computed(() =>
  session.isLoggedIn ? `Signed in as ${session.user}` : 'Not signed in',
)
</script>

<template>
  <main class="mx-auto flex min-h-full max-w-md flex-col gap-4 p-4">
    <header>
      <h1 class="text-xl font-semibold">iPay Collect</h1>
      <p class="text-sm text-gray-500">{{ greeting }}</p>
    </header>
    <Button variant="solid">It works</Button>
  </main>
</template>
