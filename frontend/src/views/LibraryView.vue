<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  audioMediaPath,
  listAudios,
  listAudioTags,
  type Audio,
  type AudioTag,
} from '@/api/audios'
import { ApiError } from '@/api/errors'
import AudioSearchBox from '@/components/AudioSearchBox.vue'
import AudioTagLines from '@/components/AudioTagLines.vue'
import TagChip from '@/components/TagChip.vue'
import { useI18n } from '@/i18n'

const { locale, t } = useI18n()
const route = useRoute()
const router = useRouter()
const audios = ref<Audio[]>([])
const localizedTags = ref<AudioTag[]>([])
const loading = ref(true)
const errorMessage = ref('')
const query = ref(typeof route.query.q === 'string' ? route.query.q : '')
const page = ref(1)
const pageSize = 20
const total = ref(0)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const tagCatalog = computed(() => {
  const tags = new Map<number, AudioTag>()
  for (const tag of localizedTags.value) tags.set(tag.id, tag)
  for (const audio of audios.value) {
    for (const tag of audio.tags) tags.set(tag.id, tag)
  }
  return [...tags.values()]
})

function formatDuration(seconds: number | null): string {
  if (seconds === null) return ''
  const rounded = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(rounded / 60)
  return `${minutes}:${String(rounded % 60).padStart(2, '0')}`
}

function speakerNames(audio: Audio): string[] {
  const utteranceNames = audio.utterances.map((utterance) => utterance.speakerDisplayName)
  const names = utteranceNames.length > 0
    ? utteranceNames
    : audio.tags
        .filter((tag) => tag.type === 'speaker')
        .map((tag) => tag.displayValue.replace(/_/g, ' '))
  return [...new Set(names)]
}

function contentTags(audio: Audio): AudioTag[] {
  return audio.tags.filter((tag) => tag.type !== 'author' && tag.type !== 'speaker')
}

async function loadPage(reset = false, syncUrl = false): Promise<void> {
  if (reset) page.value = 1
  if (syncUrl) {
    const normalizedQuery = query.value.trim()
    await router.replace({ path: '/audio', query: normalizedQuery ? { q: normalizedQuery } : {} })
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await listAudios({
      language: locale.value,
      page: page.value,
      pageSize,
      query: query.value,
      status: 'ready',
    })
    audios.value = response.items
    total.value = response.total
  } catch (error) {
    audios.value = []
    total.value = 0
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Audio could not be loaded')
  } finally {
    loading.value = false
  }
}

async function movePage(target: number): Promise<void> {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  await loadPage()
}

onMounted(async () => {
  const [, tags] = await Promise.allSettled([
    loadPage(),
    listAudioTags(locale.value),
  ])
  if (tags.status === 'fulfilled') localizedTags.value = tags.value
})
</script>

<template>
  <section class="page-shell" aria-labelledby="library-title">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('Available audio') }}</p>
        <h1 id="library-title" class="text-3xl font-semibold">{{ t('Listening library') }}</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-muted">{{ t('Browse exercises by title, speaker, topic, or category.') }}</p>
      </div>
      <span class="rounded-md bg-raised px-3 py-1.5 text-sm tabular-nums text-muted">{{ t('{count} exercises', { count: total }) }}</span>
    </div>

    <div class="my-6 rounded-md border border-line bg-surface p-4 shadow-panel sm:p-5">
      <AudioSearchBox
        v-model="query"
        :tags="tagCatalog"
        :busy="loading"
        @submit="loadPage(true, true)"
      />
    </div>

    <div v-if="loading" class="grid gap-3 md:grid-cols-2">
      <div v-for="item in 6" :key="item" class="h-40 animate-pulse rounded-md border border-line bg-surface"></div>
    </div>
    <div v-else-if="errorMessage" class="rounded-md border border-danger/30 bg-surface p-6">
      <p role="alert" class="text-sm text-danger">{{ errorMessage }}</p>
      <button
        type="button"
        class="mt-4 inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
        @click="loadPage()"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.34-5.66L20 8" stroke="currentColor" stroke-width="2" />
          <path d="M20 4v4h-4" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Retry') }}
      </button>
    </div>
    <div v-else-if="audios.length === 0" class="rounded-md border border-dashed border-line bg-surface px-6 py-12 text-center">
      <svg viewBox="0 0 24 24" fill="none" class="mx-auto h-7 w-7 text-muted" aria-hidden="true"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.7" /><path d="m16 16 4 4" stroke="currentColor" stroke-width="1.7" /></svg>
      <p class="mt-3 text-sm font-medium">{{ t('No audio found') }}</p>
      <p class="mt-1 text-sm text-muted">{{ t('Try a shorter search or remove a tag filter.') }}</p>
    </div>

    <ul v-else class="grid gap-3 md:grid-cols-2">
      <li
        v-for="audio in audios"
        :key="audio.id"
        class="flex min-w-0 flex-col rounded-md border border-line bg-surface p-5 shadow-panel transition-colors hover:border-accent/40"
      >
        <div class="min-w-0">
          <div class="flex min-w-0 flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <RouterLink
              :to="`/audio/${audio.id}`"
              class="min-w-0 flex-1 break-words text-base font-semibold leading-6 hover:text-accent"
            >
              {{ audio.title }}
            </RouterLink>
            <span v-if="audio.durationSeconds !== null" class="text-xs text-muted">
              {{ formatDuration(audio.durationSeconds) }}
            </span>
          </div>
          <RouterLink
            :to="`/user/${audio.author.userId}`"
            class="mt-1 inline-block break-words text-sm text-muted hover:text-ink"
          >
            {{ audio.author.username || audio.author.userId }}
          </RouterLink>
          <div
            v-if="speakerNames(audio).length > 0 || contentTags(audio).length > 0"
            class="mt-4 space-y-2 border-t border-line pt-4"
          >
            <ul v-if="speakerNames(audio).length > 0" class="flex min-w-0 flex-wrap gap-2">
              <li v-for="speaker in speakerNames(audio)" :key="speaker" class="flex min-w-0 max-w-full">
                <TagChip :label="speaker" :type-label="t('Speaker')" />
              </li>
            </ul>
            <AudioTagLines
              v-if="contentTags(audio).length > 0"
              :tags="contentTags(audio)"
              :include-author="false"
            />
          </div>
        </div>
        <audio
          class="mt-5 h-10 w-full"
          controls
          preload="none"
          :src="audioMediaPath(audio.id)"
        ></audio>
      </li>
    </ul>

    <nav
      v-if="!loading && totalPages > 1"
      class="mt-6 flex items-center justify-between gap-4 border-t border-line pt-5"
      :aria-label="t('Audio pages')"
    >
      <button
        type="button"
        :disabled="page <= 1"
        class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink disabled:opacity-50"
        @click="movePage(page - 1)"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Previous') }}
      </button>
      <span class="text-sm text-muted">{{ page }} / {{ totalPages }}</span>
      <button
        type="button"
        :disabled="page >= totalPages"
        class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink disabled:opacity-50"
        @click="movePage(page + 1)"
      >
        {{ t('Next') }}
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
        </svg>
      </button>
    </nav>
  </section>
</template>
