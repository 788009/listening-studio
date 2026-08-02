<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { apiRequest } from '@/api/client'
import { ApiError } from '@/api/errors'
import { useAuthStore, type CurrentUser } from '@/stores/auth'
import { useI18n } from '@/i18n'

const auth = useAuthStore()
const router = useRouter()
const { locale: activeLocale, t } = useI18n()
const userId = ref('')
const username = ref(auth.user?.suggestedUsername ?? auth.user?.username ?? '')
const locale = ref(activeLocale.value)
const errorMessage = ref('')
const userIdError = ref('')
const submitting = ref(false)

watch(userId, () => {
  userIdError.value = ''
})

async function submit(): Promise<void> {
  errorMessage.value = ''
  userIdError.value = ''
  submitting.value = true
  try {
    const user = await apiRequest<CurrentUser>('/users/me/profile', {
      method: 'POST',
      body: JSON.stringify({
        userId: userId.value,
        username: username.value || null,
        locale: locale.value,
      }),
    })
    auth.setCurrentUser(user)
    await router.replace(`/user/${user.userId}`)
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.code === 'user_id_taken' || error.code === 'user_id_immutable')
    ) {
      userIdError.value = error.message
    } else {
      errorMessage.value =
        error instanceof ApiError ? error.message : t('Profile setup failed')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="mx-auto max-w-xl" aria-labelledby="setup-title">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('Teacher account') }}</p>
        <h1 id="setup-title" class="text-3xl font-semibold">{{ t('Set up your profile') }}</h1>
      </div>
    </div>

    <form class="mt-6 space-y-5 rounded-lg border border-line bg-surface p-5 shadow-panel" @submit.prevent="submit">
      <div>
        <label for="user-id" class="mb-1 block text-sm font-medium">{{ t('User ID') }}</label>
        <input
          id="user-id"
          v-model="userId"
          required
          maxlength="64"
          pattern="[A-Za-z0-9]+"
          autocomplete="username"
          :aria-invalid="Boolean(userIdError)"
          :aria-describedby="userIdError ? 'user-id-error' : undefined"
          class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        />
        <p v-if="userIdError" id="user-id-error" role="alert" class="mt-1 text-sm text-danger">
          {{ userIdError }}
        </p>
      </div>
      <div>
        <label for="username" class="mb-1 block text-sm font-medium">{{ t('Display name') }}</label>
        <input
          id="username"
          v-model="username"
          maxlength="200"
          autocomplete="name"
          class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        />
      </div>
      <div>
        <label for="locale" class="mb-1 block text-sm font-medium">{{ t('Language') }}</label>
        <select
          id="locale"
          v-model="locale"
          class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        >
          <option value="en">{{ t('English') }}</option>
          <option value="zh-CN">{{ t('Chinese') }}</option>
        </select>
      </div>

      <p v-if="errorMessage" role="alert" class="text-sm text-danger">
        {{ errorMessage }}
      </p>
      <button
        type="submit"
        :disabled="submitting"
        class="inline-flex h-10 items-center bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
      >
        {{ submitting ? t('Saving') : t('Save profile') }}
      </button>
    </form>
  </section>
</template>
