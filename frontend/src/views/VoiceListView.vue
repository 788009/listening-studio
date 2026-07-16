<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { listVoices, type Voice } from '@/api/voices'
import { ApiError } from '@/api/errors'
import ResourceStatus from '@/components/ResourceStatus.vue'
import VoiceTagLines from '@/components/VoiceTagLines.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const voices = ref<Voice[]>([])
const loading = ref(true)
const errorMessage = ref('')
const search = ref('')

const locale = computed(() => auth.user?.locale ?? 'en')

function isOwner(voice: Voice): boolean {
  return voice.author.userId.toLowerCase() === auth.user?.userId?.toLowerCase()
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
      error instanceof ApiError ? error.message : 'Voices could not be loaded'
  } finally {
    loading.value = false
  }
}

onMounted(loadVoices)
</script>

<template>
  <section aria-labelledby="voices-title">
    <div class="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div>
        <p class="mb-1 text-sm font-medium text-accent">Teacher workspace</p>
        <h1 id="voices-title" class="text-2xl font-semibold">Voices</h1>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-muted">{{ voices.length }} available</span>
        <RouterLink
          to="/voices/create"
          class="inline-flex h-9 items-center gap-2 bg-ink px-3 text-sm font-medium text-white hover:bg-accent"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
          </svg>
          New voice
        </RouterLink>
      </div>
    </div>

    <form
      class="flex flex-col gap-3 border-b border-line py-4 sm:flex-row sm:items-end"
      role="search"
      @submit.prevent="loadVoices"
    >
      <div class="min-w-0 flex-1">
        <label for="voice-search" class="mb-1 block text-sm font-medium">Search voices</label>
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
        Search
      </button>
    </form>

    <p v-if="loading" class="border-b border-line py-12 text-sm text-muted">
      Loading voices
    </p>
    <div v-else-if="errorMessage" class="border-b border-line py-10">
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
        Retry
      </button>
    </div>
    <p v-else-if="voices.length === 0" class="border-b border-line py-12 text-sm text-muted">
      No voices found
    </p>

    <ul v-else class="divide-y divide-line border-b border-line bg-surface">
      <li v-for="voice in voices" :key="voice.id">
        <RouterLink
          :to="`/voice/${voice.id}`"
          class="group grid min-w-0 gap-4 px-4 py-5 hover:bg-canvas sm:grid-cols-[minmax(0,1.25fr)_minmax(12rem,1fr)_8rem_1.5rem] sm:items-center sm:px-5"
        >
          <div class="min-w-0">
            <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <h2 class="min-w-0 break-words text-base font-semibold">{{ voice.title }}</h2>
              <span v-if="isOwner(voice)" class="text-xs font-medium text-accent">Yours</span>
            </div>
            <p class="mt-1 break-words text-sm text-muted">
              {{ voice.author.username || voice.author.userId }}
            </p>
          </div>
          <VoiceTagLines :tags="voice.tags" />
          <div class="flex min-w-0 flex-row items-center gap-4 sm:flex-col sm:items-start sm:gap-2">
            <ResourceStatus :status="voice.status" />
            <span class="text-sm capitalize text-muted">{{ voice.visibility }}</span>
          </div>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            class="hidden h-5 w-5 text-muted group-hover:text-ink sm:block"
            aria-hidden="true"
          >
            <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
          </svg>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
