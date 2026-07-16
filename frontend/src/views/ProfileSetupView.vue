<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { apiRequest } from '@/api/client'
import { ApiError } from '@/api/errors'
import { useAuthStore, type CurrentUser } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const userId = ref('')
const username = ref('')
const locale = ref('en')
const errorMessage = ref('')
const submitting = ref(false)

async function submit(): Promise<void> {
  errorMessage.value = ''
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
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Profile setup failed'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="mx-auto max-w-xl" aria-labelledby="setup-title">
    <div class="border-b border-line pb-5">
      <p class="mb-1 text-sm font-medium text-accent">Teacher account</p>
      <h1 id="setup-title" class="text-2xl font-semibold">Set up your profile</h1>
    </div>

    <form class="space-y-5 border-b border-line bg-surface py-6" @submit.prevent="submit">
      <div>
        <label for="user-id" class="mb-1 block text-sm font-medium">User ID</label>
        <input
          id="user-id"
          v-model="userId"
          required
          maxlength="64"
          pattern="[A-Za-z0-9]+"
          autocomplete="username"
          class="h-10 w-full border border-line bg-white px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        />
      </div>
      <div>
        <label for="username" class="mb-1 block text-sm font-medium">Display name</label>
        <input
          id="username"
          v-model="username"
          maxlength="200"
          autocomplete="name"
          class="h-10 w-full border border-line bg-white px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        />
      </div>
      <div>
        <label for="locale" class="mb-1 block text-sm font-medium">Language</label>
        <select
          id="locale"
          v-model="locale"
          class="h-10 w-full border border-line bg-white px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        >
          <option value="en">English</option>
          <option value="zh-CN">Chinese</option>
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
        {{ submitting ? 'Saving' : 'Save profile' }}
      </button>
    </form>
  </section>
</template>
