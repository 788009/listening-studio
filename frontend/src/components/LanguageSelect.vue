<script setup lang="ts">
import { ref } from 'vue'

import { apiRequest } from '@/api/client'
import { type CurrentUser, useAuthStore } from '@/stores/auth'
import { useI18n, type SupportedLocale } from '@/i18n'
import { usePreferencesStore } from '@/stores/preferences'

const auth = useAuthStore()
const preferences = usePreferencesStore()
const { locale, t } = useI18n()
const saving = ref(false)
const errorMessage = ref('')

async function selectLanguage(event: Event): Promise<void> {
  const nextLanguage = (event.target as HTMLSelectElement).value as SupportedLocale
  const previousLanguage = locale.value
  errorMessage.value = ''
  preferences.setLanguage(nextLanguage)

  if (!auth.user?.profileComplete) return

  saving.value = true
  try {
    const user = await apiRequest<CurrentUser>('/users/me/profile', {
      method: 'PATCH',
      body: JSON.stringify({ locale: nextLanguage }),
    })
    auth.setCurrentUser(user)
  } catch {
    preferences.setLanguage(previousLanguage)
    errorMessage.value = t('Language update failed')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <span class="relative inline-flex items-center">
    <select
      :value="locale"
      :disabled="saving"
      :aria-label="t('Language')"
      :title="t('Language')"
      class="h-9 w-20 border border-line bg-surface px-2 text-sm text-ink transition-colors hover:border-ink focus:border-accent focus:outline-none focus:shadow-focus disabled:opacity-60 sm:w-24"
      @change="selectLanguage"
    >
      <option value="en">English</option>
      <option value="zh-CN">中文</option>
    </select>
    <span
      v-if="errorMessage"
      role="alert"
      class="absolute right-0 top-full z-40 mt-1 w-52 border border-danger/40 bg-surface px-3 py-2 text-xs text-danger shadow-panel"
    >
      {{ errorMessage }}
    </span>
  </span>
</template>
