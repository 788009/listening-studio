<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { listAudios, type Audio } from '@/api/audios'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { locale, t } = useI18n()
const query = ref('')
const recentAudios = ref<Audio[]>([])
const loading = ref(true)
const waveform = [28, 50, 35, 72, 46, 88, 58, 34, 67, 44, 78, 52, 30, 62, 42, 70, 48, 26]

function search(): void {
  const value = query.value.trim()
  router.push({ path: '/audio', query: value ? { q: value } : {} })
}

function duration(seconds: number | null): string {
  if (seconds === null) return t('Open audio')
  const rounded = Math.max(0, Math.round(seconds))
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

function category(audio: Audio): string {
  const tag = audio.tags.find((item) => item.type === 'topic' || item.type === 'category')
  return tag?.displayValue.replace(/_/g, ' ') ?? t('Listening practice')
}

onMounted(async () => {
  try {
    const response = await listAudios({
      language: locale.value,
      pageSize: 4,
      status: 'ready',
      visibility: 'public',
    })
    recentAudios.value = response.items
  } catch {
    recentAudios.value = []
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="space-y-10 sm:space-y-12">
    <section class="grid min-h-[21rem] items-center gap-8 border-b border-line pb-10 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-14" aria-labelledby="home-title">
      <div class="min-w-0">
        <p class="eyebrow">{{ t('Home') }}</p>
        <h1 id="home-title" class="text-3xl font-semibold leading-tight sm:text-4xl">Listening Studio</h1>
        <p class="mt-3 max-w-2xl text-base leading-7 text-muted">
          {{ t('Search the public library or continue your listening work.') }}
        </p>

        <form class="mt-7 flex max-w-2xl flex-col gap-2 sm:flex-row" role="search" @submit.prevent="search">
          <label for="home-search" class="sr-only">{{ t('Search audio') }}</label>
          <div class="relative min-w-0 flex-1">
            <svg viewBox="0 0 24 24" fill="none" class="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-muted" aria-hidden="true">
              <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8" />
              <path d="m16 16 4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
            <input
              id="home-search"
              v-model="query"
              type="search"
              maxlength="1024"
              :placeholder="t('Search by title, topic, or speaker')"
              class="h-12 w-full border border-line bg-surface pl-10 pr-3 text-sm shadow-panel focus:border-accent focus:outline-none focus:shadow-focus"
            />
          </div>
          <button type="submit" class="inline-flex h-12 shrink-0 items-center justify-center bg-ink px-5 text-sm font-medium text-white transition-colors hover:bg-accent">
            {{ t('Search') }}
          </button>
        </form>

        <div class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <RouterLink to="/audio" class="inline-flex items-center gap-1.5 font-medium text-accent hover:underline">
            {{ t('Browse all audio') }}
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>
          </RouterLink>
          <RouterLink v-if="auth.isTeacher" to="/create" class="font-medium text-muted hover:text-ink">
            {{ t('Create new audio') }}
          </RouterLink>
        </div>
      </div>

      <div class="hidden h-44 items-center lg:flex" aria-hidden="true">
        <div class="flex h-full w-full items-center justify-center gap-2 border-y border-line">
          <span
            v-for="(height, index) in waveform"
            :key="index"
            class="w-1 rounded-full bg-accent"
            :style="{ height: `${height}%`, opacity: String(0.35 + (index % 4) * 0.15) }"
          ></span>
        </div>
      </div>
    </section>

    <section v-if="auth.isTeacher" aria-labelledby="quick-actions-title">
      <div class="mb-4 flex items-center justify-between gap-4">
        <h2 id="quick-actions-title" class="text-base font-semibold">{{ t('Continue working') }}</h2>
        <span class="text-xs text-muted">{{ t('Teacher workspace') }}</span>
      </div>
      <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <RouterLink to="/create" class="group flex items-center gap-3 rounded-md border border-line bg-surface px-4 py-3.5 shadow-panel transition-colors hover:border-accent/50 hover:bg-raised">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent"><svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg></span>
          <span class="min-w-0"><span class="block text-sm font-semibold">{{ t('Create audio') }}</span><span class="mt-0.5 block truncate text-xs text-muted">{{ t('Single speaker or dialogue') }}</span></span>
        </RouterLink>
        <RouterLink to="/generate" class="group flex items-center gap-3 rounded-md border border-line bg-surface px-4 py-3.5 shadow-panel transition-colors hover:border-accent/50 hover:bg-raised">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-raised text-muted"><svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg></span>
          <span class="min-w-0"><span class="block text-sm font-semibold">{{ t('Batch') }}</span><span class="mt-0.5 block truncate text-xs text-muted">{{ t('Generate a set of exercises') }}</span></span>
        </RouterLink>
        <RouterLink to="/papers/new" class="group flex items-center gap-3 rounded-md border border-line bg-surface px-4 py-3.5 shadow-panel transition-colors hover:border-accent/50 hover:bg-raised">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-raised text-muted"><svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M7 4h10v16H7V4Z" stroke="currentColor" stroke-width="1.8" /><path d="M10 9h4M10 13h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg></span>
          <span class="min-w-0"><span class="block text-sm font-semibold">{{ t('Papers') }}</span><span class="mt-0.5 block truncate text-xs text-muted">{{ t('Arrange listening sections') }}</span></span>
        </RouterLink>
        <RouterLink to="/manage" class="group flex items-center gap-3 rounded-md border border-line bg-surface px-4 py-3.5 shadow-panel transition-colors hover:border-accent/50 hover:bg-raised">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-raised text-muted"><svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M5 7h14M7 12h10M9 17h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg></span>
          <span class="min-w-0"><span class="block text-sm font-semibold">{{ t('Manage') }}</span><span class="mt-0.5 block truncate text-xs text-muted">{{ t('Review your resources') }}</span></span>
        </RouterLink>
      </div>
    </section>

    <section aria-labelledby="recent-title">
      <div class="mb-5 flex items-end justify-between gap-4">
        <div>
          <p class="eyebrow">{{ t('Ready to listen') }}</p>
          <h2 id="recent-title" class="text-xl font-semibold">{{ t('Recent audio') }}</h2>
        </div>
        <RouterLink to="/audio" class="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-ink">
          {{ t('View library') }}
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
        </RouterLink>
      </div>

      <div v-if="loading" class="grid gap-3 sm:grid-cols-2">
        <div v-for="item in 4" :key="item" class="h-24 animate-pulse rounded-md border border-line bg-surface"></div>
      </div>
      <div v-else-if="recentAudios.length" class="grid gap-3 sm:grid-cols-2">
        <RouterLink
          v-for="audio in recentAudios"
          :key="audio.id"
          :to="`/audio/${audio.id}`"
          class="group flex min-w-0 items-center gap-4 rounded-md border border-line bg-surface p-4 shadow-panel transition-colors hover:border-accent/50 hover:bg-raised"
        >
          <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
            <svg viewBox="0 0 24 24" fill="none" class="h-5 w-5" aria-hidden="true"><path d="m9 7 8 5-8 5V7Z" fill="currentColor" /></svg>
          </span>
          <span class="min-w-0 flex-1"><span class="block truncate text-sm font-semibold group-hover:text-accent">{{ audio.title }}</span><span class="mt-1 block truncate text-xs text-muted">{{ category(audio) }}</span></span>
          <span class="shrink-0 text-xs tabular-nums text-muted">{{ duration(audio.durationSeconds) }}</span>
        </RouterLink>
      </div>
      <div v-else class="rounded-md border border-dashed border-line bg-surface px-5 py-8">
        <h3 class="text-sm font-semibold">{{ t('No public audio yet') }}</h3>
        <p class="mt-1 text-sm text-muted">{{ t('Public audio will appear here.') }}</p>
      </div>
    </section>
  </div>
</template>
