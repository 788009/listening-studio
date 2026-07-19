<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'
import { usePreferencesStore } from '@/stores/preferences'

const preferences = usePreferencesStore()
const { t } = useI18n()
const label = computed(() =>
  preferences.resolvedTheme === 'dark' ? t('Use light theme') : t('Use dark theme'),
)
</script>

<template>
  <button
    type="button"
    class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-raised hover:text-ink"
    :aria-label="label"
    :title="label"
    @click="preferences.toggleTheme"
  >
    <svg
      v-if="preferences.resolvedTheme === 'dark'"
      viewBox="0 0 24 24"
      fill="none"
      class="h-[18px] w-[18px]"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
    </svg>
    <svg v-else viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true">
      <path d="M20.2 15.1A8.2 8.2 0 0 1 8.9 3.8 8.2 8.2 0 1 0 20.2 15.1Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
    </svg>
  </button>
</template>
