<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

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
import { useI18n } from '@/i18n'

const { locale, t } = useI18n()
const audios = ref<Audio[]>([])
const localizedTags = ref<AudioTag[]>([])
const loading = ref(true)
const errorMessage = ref('')
const query = ref('')
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

async function loadPage(reset = false): Promise<void> {
  if (reset) page.value = 1
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await listAudios({
      language: locale.value,
      page: page.value,
      pageSize,
      query: query.value,
      status: 'ready',
      visibility: 'public',
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
  <section aria-labelledby="library-title">
    <div class="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div>
        <p class="mb-1 text-sm font-medium text-accent">{{ t('Public audio') }}</p>
        <h1 id="library-title" class="text-2xl font-semibold">{{ t('Listening library') }}</h1>
      </div>
      <span class="text-sm text-muted">{{ t('{count} exercises', { count: total }) }}</span>
    </div>

    <div class="border-b border-line py-4">
      <AudioSearchBox
        v-model="query"
        :tags="tagCatalog"
        :busy="loading"
        @submit="loadPage(true)"
      />
    </div>

    <p v-if="loading" class="border-b border-line py-12 text-sm text-muted">
      {{ t('Loading audio') }}
    </p>
    <div v-else-if="errorMessage" class="border-b border-line py-10">
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
    <p v-else-if="audios.length === 0" class="border-b border-line py-12 text-sm text-muted">
      {{ t('No audio found') }}
    </p>

    <ul v-else class="divide-y divide-line border-b border-line bg-surface">
      <li
        v-for="audio in audios"
        :key="audio.id"
        class="grid min-w-0 gap-5 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_minmax(15rem,0.8fr)] lg:items-center lg:px-5"
      >
        <div class="min-w-0">
          <div class="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
            <RouterLink
              :to="`/audio/${audio.id}`"
              class="min-w-0 break-words text-base font-semibold hover:text-accent hover:underline"
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
          <div class="mt-4">
            <AudioTagLines :tags="audio.tags" />
          </div>
        </div>
        <audio
          class="h-10 w-full"
          controls
          preload="none"
          :src="audioMediaPath(audio.id)"
        ></audio>
      </li>
    </ul>

    <nav
      v-if="!loading && totalPages > 1"
      class="flex items-center justify-between gap-4 border-b border-line py-4"
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
