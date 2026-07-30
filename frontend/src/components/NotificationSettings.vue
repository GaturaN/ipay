<script setup>
import { ref } from 'vue'
import BaseDialog from './BaseDialog.vue'
import { usePushNotifications } from '@/composables/usePushNotifications'

const open = ref(false)
const {
  supported,
  configured,
  blocked,
  subscribed,
  busy,
  error,
  prefs,
  testStatus,
  refresh,
  enable,
  disable,
  updatePref,
  test,
} = usePushNotifications()

const OPTIONS = [
  { key: 'notify_cheque_assigned', label: 'Cheque collection assigned to me' },
  { key: 'notify_collection_success', label: 'Successful collection' },
  { key: 'notify_collection_error', label: 'Collection error' },
  { key: 'notify_comment', label: 'New note on a customer' },
]

const TEST_MESSAGE = {
  sending: 'Sending…',
  sent: 'Test sent — check your notifications (or Notification Center).',
  none: 'No active device found for this login.',
  error: "Couldn't send the test — please try again.",
}

async function show() {
  open.value = true
  await refresh()
}
</script>

<template>
  <button
    type="button"
    aria-label="Notification settings"
    class="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-hairline bg-white text-ink/70 transition active:bg-paper"
    @click="show"
  >
    <svg viewBox="0 0 20 20" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M10 3a4 4 0 0 0-4 4c0 4-1.5 5-1.5 5h11S14 11 14 7a4 4 0 0 0-4-4Z" stroke-linejoin="round" />
      <path d="M8.5 15a1.5 1.5 0 0 0 3 0" stroke-linecap="round" />
    </svg>
  </button>

  <BaseDialog :open="open" labelledby="notif-title" focus="panel" @close="open = false">
    <h2 id="notif-title" class="font-display text-lg font-semibold text-ink">Notifications</h2>

    <p v-if="!supported" class="mt-3 text-sm text-ink/70">
      This browser doesn't support notifications. On an iPhone, add iPay Collect to your home
      screen first, then open it from there.
    </p>

    <p v-else-if="blocked" class="mt-3 text-sm text-ink/70">
      Notifications are blocked for this site. Turn them back on in your browser's site settings,
      then reopen this panel.
    </p>

    <template v-else-if="!subscribed">
      <p class="mt-3 text-sm text-ink/70">
        Get alerted when a cheque collection is assigned to you, and when a collection succeeds or
        fails. You choose what to receive, and can turn it off any time.
      </p>
      <p v-if="!configured" class="mt-3 rounded-xl bg-owed/10 px-3 py-2.5 text-[13px] font-medium text-owed">
        Notifications aren't set up on the server yet — ask an administrator to configure them.
      </p>
      <button
        type="button"
        class="mt-5 h-12 w-full rounded-xl bg-mpesa font-semibold text-white transition active:scale-[.98] disabled:opacity-50"
        :disabled="busy || !configured"
        @click="enable"
      >
        {{ busy ? 'Turning on…' : 'Turn on notifications' }}
      </button>
      <p v-if="error" class="mt-2 text-sm text-danger">{{ error }}</p>
    </template>

    <template v-else>
      <p class="mt-3 text-sm text-ink/70">Choose what you'd like to be notified about.</p>
      <div class="mt-4 flex flex-col gap-1">
        <label
          v-for="opt in OPTIONS"
          :key="opt.key"
          class="flex cursor-pointer items-center justify-between gap-3 rounded-xl px-1 py-2.5"
        >
          <span class="text-sm text-ink">{{ opt.label }}</span>
          <input
            type="checkbox"
            class="h-5 w-5 accent-mpesa"
            :checked="Boolean(prefs[opt.key])"
            @change="updatePref(opt.key, $event.target.checked)"
          />
        </label>
      </div>

      <div class="mt-5 flex gap-2">
        <button
          type="button"
          class="h-11 flex-1 rounded-xl border border-hairline font-medium text-ink/80 transition active:bg-paper"
          @click="test"
        >
          Send a test
        </button>
        <button
          type="button"
          class="h-11 flex-1 rounded-xl border border-hairline font-medium text-danger transition active:bg-paper disabled:opacity-50"
          :disabled="busy"
          @click="disable"
        >
          Turn off
        </button>
      </div>
      <p v-if="testStatus" class="mt-2 text-center text-[13px] text-ink/70">
        {{ TEST_MESSAGE[testStatus] }}
      </p>
    </template>
  </BaseDialog>
</template>
