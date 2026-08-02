<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { listVoices, type Voice } from '@/api/voices'
import { ApiError } from '@/api/errors'
import AuthorLink from '@/components/AuthorLink.vue'
import ResourceStatus from '@/components/ResourceStatus.vue'
import VoiceTagLines from '@/components/VoiceTagLines.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const auth = useAuthStore()
const route = useRoute()
const { locale, t } = useI18n()
const voices = ref<Voice[]>([])
const loading = ref(true)
const errorMessage = ref('')
const search = ref(typeof route.query.q === 'string' ? route.query.q : '')

function isOwner(voice: Voice): boolean {
  return voice.author.userId.toLowerCase() === auth.user?.userId?.toLowerCase()
}

function statusLabel(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

async function loadVoices(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await listVoices({
      language: locale.value,
      query: search.value,
    })
    voices.value = response.items
  } catch (error) {
    voices.value = []
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Voices could not be loaded')
  } finally {
    loading.value = false
  }
}

onMounted(loadVoices)
</script>

<template>
  <section class="page-shell" aria-labelledby="voices-title">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('Teacher workspace') }}</p>
        <h1 id="voices-title" class="text-3xl font-semibold">{{ t('Voices') }}</h1>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-muted">{{ t('{count} available', { count: voices.length }) }}</span>
        <RouterLink
          to="/voices/create"
          class="inline-flex h-9 items-center gap-2 bg-ink px-3 text-sm font-medium text-white hover:bg-accent"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
          </svg>
          {{ t('New voice') }}
        </RouterLink>
      </div>
    </div>

    <form
      class="my-6 flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 shadow-panel sm:flex-row sm:items-end"
      role="search"
      @submit.prevent="loadVoices"
    >
      <div class="min-w-0 flex-1">
        <label for="voice-search" class="mb-1 block text-sm font-medium">{{ t('Search voices') }}</label>
        <input
          id="voice-search"
          v-model="search"
          type="search"
          maxlength="1024"
          class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        />
      </div>
      <button
        type="submit"
        class="inline-flex h-10 shrink-0 items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" />
          <path d="m16 16 4 4" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Search') }}
      </button>
    </form>

    <p v-if="loading" class="rounded-lg border border-line bg-surface px-5 py-12 text-sm text-muted">
      {{ t('Loading voices') }}
    </p>
    <div v-else-if="errorMessage" class="rounded-lg border border-danger/30 bg-surface p-5">
      <p role="alert" class="text-sm text-danger">{{ errorMessage }}</p>
      <button
        type="button"
        class="mt-4 inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
        @click="loadVoices"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.34-5.66L20 8" stroke="currentColor" stroke-width="2" />
          <path d="M20 4v4h-4" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Retry') }}
      </button>
    </div>
    <p v-else-if="voices.length === 0" class="rounded-lg border border-dashed border-line bg-surface px-5 py-12 text-center text-sm text-muted">
      {{ t('No voices found') }}
    </p>

    <ul v-else class="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-panel">
      <li
        v-for="voice in voices"
        :key="voice.id"
        class="group grid min-w-0 gap-4 px-4 py-5 hover:bg-canvas sm:grid-cols-[minmax(0,1.25fr)_minmax(12rem,1fr)_8rem_1.5rem] sm:items-center sm:px-5"
      >
        <div class="min-w-0">
          <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <RouterLink
              :to="`/voice/${voice.id}`"
              class="min-w-0 break-words text-base font-semibold hover:text-accent"
            >
              {{ voice.title }}
            </RouterLink>
            <span v-if="isOwner(voice)" class="text-xs font-medium text-accent">{{ t('Yours') }}</span>
          </div>
          <AuthorLink :author="voice.author" class="mt-1 text-sm" />
        </div>
        <VoiceTagLines
          :tags="voice.tags"
          :author="voice.author"
          :include-author="false"
          search-path="/voices"
        />
        <div class="flex min-w-0 flex-row items-center gap-4 sm:flex-col sm:items-start sm:gap-2">
          <ResourceStatus :status="voice.status" />
          <span class="text-sm capitalize text-muted">{{ t(statusLabel(voice.visibility)) }}</span>
        </div>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          class="hidden h-5 w-5 text-muted group-hover:text-ink sm:block"
          aria-hidden="true"
        >
          <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
        </svg>
      </li>
    </ul>
  </section>
</template>
