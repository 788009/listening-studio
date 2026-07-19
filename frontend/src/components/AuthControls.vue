<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/errors'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const dialogOpen = ref(false)
const issuer = ref('https://local-debug.example')
const subject = ref('')
const subjectInput = ref<HTMLInputElement | null>(null)
const submitting = ref(false)
const errorMessage = ref('')

const accountLabel = computed(
  () => auth.user?.username || auth.user?.userId || t('Set up profile'),
)

onMounted(async () => {
  try {
    await auth.loadCapabilities()
  } catch {
    // Authentication controls stay unavailable when capability discovery fails.
  }
})

async function beginSignIn(): Promise<void> {
  if (auth.capabilities.loginMethod === 'redirect' && auth.capabilities.loginUrl) {
    window.location.assign(auth.capabilities.loginUrl)
    return
  }
  if (auth.capabilities.loginMethod !== 'debug') {
    return
  }
  errorMessage.value = ''
  dialogOpen.value = true
  await nextTick()
  subjectInput.value?.focus()
}

function closeDialog(): void {
  if (submitting.value) return
  dialogOpen.value = false
  errorMessage.value = ''
}

async function submitDebugSignIn(): Promise<void> {
  submitting.value = true
  errorMessage.value = ''
  try {
    const user = await auth.signInDebug({
      issuer: issuer.value,
      subject: subject.value,
    })
    dialogOpen.value = false
    if (user.profileComplete && user.userId) {
      await router.replace(`/user/${user.userId}`)
    } else {
      await router.replace('/setup-profile')
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Sign in failed')
  } finally {
    submitting.value = false
  }
}

async function signOut(): Promise<void> {
  errorMessage.value = ''
  try {
    const redirectUrl = await auth.signOut()
    if (redirectUrl) {
      window.location.assign(redirectUrl)
      return
    }
    await router.replace('/')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Sign out failed')
  }
}
</script>

<template>
  <div class="flex flex-col items-end gap-1 lg:w-full lg:items-stretch">
    <div class="flex min-h-9 items-center gap-1 lg:w-full lg:gap-2">
      <template v-if="auth.isTeacher">
        <RouterLink
          :to="auth.profileComplete && auth.user?.userId ? `/user/${auth.user.userId}` : '/setup-profile'"
          class="flex h-9 min-w-0 items-center gap-2 rounded-md px-1.5 text-sm font-medium text-ink hover:bg-raised hover:text-accent lg:flex-1"
          :title="accountLabel"
        >
          <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-soft text-xs font-semibold uppercase text-accent">{{ accountLabel.slice(0, 1) }}</span>
          <span class="hidden min-w-0 truncate lg:block">{{ accountLabel }}</span>
        </RouterLink>
        <button
          type="button"
          class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted hover:bg-raised hover:text-ink disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="submitting"
          :aria-label="t('Sign out')"
          :title="t('Sign out')"
          @click="signOut"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true">
            <path d="M14 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            <path d="M10 12h11m0 0-3-3m3 3-3 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </template>
      <button
        v-else-if="auth.capabilities.loginMethod !== 'none'"
        type="button"
        class="h-9 rounded-md bg-ink px-3 text-sm font-medium text-white hover:bg-accent lg:w-full"
        @click="beginSignIn"
      >
        {{ t('Sign in') }}
      </button>
    </div>
    <p v-if="errorMessage && !dialogOpen" role="alert" class="max-w-64 text-sm text-danger">
      {{ errorMessage }}
    </p>

    <div
      v-if="dialogOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="closeDialog"
      @keydown.esc="closeDialog"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="debug-sign-in-title"
        class="w-full max-w-md rounded-lg border border-line bg-surface p-5 shadow-xl"
      >
        <h2 id="debug-sign-in-title" class="text-lg font-semibold">
          {{ t('Development sign in') }}
        </h2>
        <form class="mt-5 space-y-4" @submit.prevent="submitDebugSignIn">
          <div>
            <label for="debug-issuer" class="mb-1 block text-sm font-medium">
              {{ t('Issuer') }}
            </label>
            <input
              id="debug-issuer"
              v-model="issuer"
              required
              maxlength="2048"
              class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            />
          </div>
          <div>
            <label for="debug-subject" class="mb-1 block text-sm font-medium">
              {{ t('Subject') }}
            </label>
            <input
              id="debug-subject"
              ref="subjectInput"
              v-model="subject"
              required
              maxlength="255"
              autocomplete="username"
              class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            />
          </div>
          <p v-if="errorMessage" role="alert" class="text-sm text-danger">
            {{ errorMessage }}
          </p>
          <div class="flex justify-end gap-2 pt-1">
            <button
              type="button"
              class="h-9 border border-line px-3 text-sm font-medium hover:border-muted"
              :disabled="submitting"
              @click="closeDialog"
            >
              {{ t('Cancel') }}
            </button>
            <button
              type="submit"
              class="h-9 bg-ink px-3 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="submitting"
            >
              {{ submitting ? t('Signing in') : t('Sign in') }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </div>
</template>
