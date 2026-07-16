<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { apiRequest } from '@/api/client'
import { ApiError } from '@/api/errors'
import { useAuthStore, type CurrentUser } from '@/stores/auth'
import { useI18n } from '@/i18n'

interface UserSummary {
  userId: string
  username: string | null
  locale: string
  createdAt: string
  statistics: {
    publicVoiceCount: number
    publicAudioCount: number
  }
  privateStatistics?: {
    privateVoiceCount: number
    privateAudioCount: number
  }
}

const route = useRoute()
const auth = useAuthStore()
const { t } = useI18n()
const profile = ref<UserSummary | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const editing = ref(false)
const username = ref('')
const locale = ref('en')

const isCurrentUser = computed(
  () => auth.user?.userId?.toLowerCase() === profile.value?.userId.toLowerCase(),
)

async function loadProfile(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    profile.value = await apiRequest<UserSummary>(
      `/users/${String(route.params.userId)}`,
    )
    username.value = profile.value.username ?? ''
    locale.value = profile.value.locale
  } catch (error) {
    profile.value = null
    errorMessage.value = error instanceof ApiError ? error.message : t('Profile unavailable')
  } finally {
    loading.value = false
  }
}

async function saveProfile(): Promise<void> {
  errorMessage.value = ''
  try {
    const currentUser = await apiRequest<CurrentUser>('/users/me/profile', {
      method: 'PATCH',
      body: JSON.stringify({ username: username.value, locale: locale.value }),
    })
    auth.setCurrentUser(currentUser)
    editing.value = false
    await loadProfile()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Profile update failed')
  }
}

watch(() => route.params.userId, loadProfile, { immediate: true })
</script>

<template>
  <section aria-labelledby="profile-title">
    <p v-if="loading" class="py-12 text-sm text-muted">{{ t('Loading profile') }}</p>
    <p v-else-if="errorMessage && !profile" role="alert" class="py-12 text-sm text-danger">
      {{ errorMessage }}
    </p>

    <template v-else-if="profile">
      <div class="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
        <div>
          <p class="mb-1 text-sm font-medium text-accent">@{{ profile.userId }}</p>
          <h1 id="profile-title" class="text-2xl font-semibold">
            {{ profile.username || profile.userId }}
          </h1>
        </div>
        <button
          v-if="isCurrentUser && !editing"
          type="button"
          class="h-9 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
          @click="editing = true"
        >
          {{ t('Edit profile') }}
        </button>
      </div>

      <form
        v-if="editing"
        class="grid gap-4 border-b border-line bg-surface py-6 sm:grid-cols-[1fr_12rem_auto] sm:items-end"
        @submit.prevent="saveProfile"
      >
        <div>
          <label for="edit-username" class="mb-1 block text-sm font-medium">{{ t('Display name') }}</label>
          <input
            id="edit-username"
            v-model="username"
            required
            maxlength="200"
            class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>
        <div>
          <label for="edit-locale" class="mb-1 block text-sm font-medium">{{ t('Language') }}</label>
          <select
            id="edit-locale"
            v-model="locale"
            class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          >
            <option value="en">{{ t('English') }}</option>
            <option value="zh-CN">{{ t('Chinese') }}</option>
          </select>
        </div>
        <button type="submit" class="h-10 bg-ink px-4 text-sm font-medium text-white hover:bg-accent">
          {{ t('Save') }}
        </button>
        <p v-if="errorMessage" role="alert" class="text-sm text-danger sm:col-span-3">
          {{ errorMessage }}
        </p>
      </form>

      <dl class="grid border-b border-line bg-surface sm:grid-cols-2">
        <div class="border-b border-line px-5 py-6 sm:border-b-0 sm:border-r">
          <dt class="text-sm text-muted">{{ t('Public voices') }}</dt>
          <dd class="mt-1 text-2xl font-semibold">{{ profile.statistics.publicVoiceCount }}</dd>
        </div>
        <div class="px-5 py-6">
          <dt class="text-sm text-muted">{{ t('Public audio count') }}</dt>
          <dd class="mt-1 text-2xl font-semibold">{{ profile.statistics.publicAudioCount }}</dd>
        </div>
      </dl>
    </template>
  </section>
</template>
