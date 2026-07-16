<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  audioMediaPath,
  getAudio,
  listAudios,
  listAudioTags,
  type Audio,
  type AudioTag,
} from '@/api/audios'
import { ApiError } from '@/api/errors'
import { cancelJob, getJob, type Job, type JobStatus } from '@/api/jobs'
import {
  createPaper,
  listPaperPresets,
  renderPaper,
  type PaperPreset,
  type PaperRenderAccepted,
} from '@/api/papers'
import AudioSearchBox from '@/components/AudioSearchBox.vue'
import PaperSelectedAudioList from '@/components/PaperSelectedAudioList.vue'
import type { PaperSelection } from '@/components/paperSelectionTypes'
import { useAuthStore } from '@/stores/auth'

const PAGE_SIZE = 10
const router = useRouter()
const auth = useAuthStore()
const title = ref('')
const presets = ref<PaperPreset[]>([])
const presetId = ref('')
const candidates = ref<Audio[]>([])
const tags = ref<AudioTag[]>([])
const selected = ref<PaperSelection[]>([])
const query = ref('')
const page = ref(1)
const total = ref(0)
const loadingOptions = ref(true)
const loadingCandidates = ref(true)
const validating = ref(false)
const submitting = ref(false)
const cancelling = ref(false)
const errorMessage = ref('')
const accepted = ref<PaperRenderAccepted | null>(null)
const job = ref<Job | null>(null)
let pollTimer: number | undefined

const locale = computed(() => auth.user?.locale ?? 'en')
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const selectedPreset = computed(
  () => presets.value.find((preset) => String(preset.id) === presetId.value) ?? null,
)
const tagCatalog = computed(() => {
  const catalog = new Map<number, AudioTag>()
  for (const tag of tags.value) catalog.set(tag.id, tag)
  for (const audio of candidates.value) {
    for (const tag of audio.tags) catalog.set(tag.id, tag)
  }
  return [...catalog.values()]
})
const selectedIds = computed(() => new Set(selected.value.map((item) => item.audio.id)))
const invalidSelection = computed(() =>
  selected.value.some((item) => item.state !== 'valid'),
)
const estimatedDuration = computed(() => {
  const preset = selectedPreset.value
  if (!preset || selected.value.some((item) => item.audio.durationSeconds === null)) {
    return null
  }
  const sourceSeconds = selected.value.reduce(
    (sum, item) => sum + (item.audio.durationSeconds ?? 0),
    0,
  )
  return (
    sourceSeconds * preset.repeatCount +
    preset.introSilenceMilliseconds / 1000 +
    preset.outroSilenceMilliseconds / 1000 +
    (Math.max(0, selected.value.length - 1) *
      preset.interItemSilenceMilliseconds) /
      1000
  )
})

async function loadOptions(): Promise<void> {
  loadingOptions.value = true
  try {
    const [presetResponse, tagResponse] = await Promise.all([
      listPaperPresets(),
      listAudioTags(locale.value),
    ])
    presets.value = presetResponse
    tags.value = tagResponse
    if (!presetId.value && presetResponse[0]) {
      presetId.value = String(presetResponse[0].id)
    }
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Paper options could not be loaded'
  } finally {
    loadingOptions.value = false
  }
}

async function loadCandidates(reset = false): Promise<void> {
  if (reset) page.value = 1
  loadingCandidates.value = true
  errorMessage.value = ''
  try {
    const response = await listAudios({
      language: locale.value,
      page: page.value,
      pageSize: PAGE_SIZE,
      query: query.value,
      status: 'ready',
    })
    candidates.value = response.items
    total.value = response.total
  } catch (error) {
    candidates.value = []
    total.value = 0
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Audio candidates could not be loaded'
  } finally {
    loadingCandidates.value = false
  }
}

async function movePage(target: number): Promise<void> {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  await loadCandidates()
}

function addAudio(audio: Audio): void {
  if (selectedIds.value.has(audio.id) || selected.value.length >= 100) return
  selected.value = [...selected.value, { audio, state: 'valid' }]
}

function moveAudio(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= selected.value.length) return
  const next = [...selected.value]
  const [item] = next.splice(index, 1)
  if (!item) return
  next.splice(target, 0, item)
  selected.value = next
}

function removeAudio(index: number): void {
  selected.value = selected.value.filter((_, position) => position !== index)
}

async function validateSelections(): Promise<boolean> {
  if (selected.value.length === 0 || validating.value) return false
  validating.value = true
  const current = selected.value.map((item) => ({
    ...item,
    state: 'checking' as const,
    message: 'Checking access and status',
  }))
  selected.value = current
  const results = await Promise.all(
    current.map(async (item): Promise<PaperSelection> => {
      try {
        const audio = await getAudio(item.audio.id, locale.value)
        if (audio.status !== 'ready') {
          return {
            audio,
            state: 'changed',
            message: `Status changed to ${statusLabel(audio.status)}`,
          }
        }
        return { audio, state: 'valid' }
      } catch (error) {
        const inaccessible = error instanceof ApiError && [403, 404].includes(error.status)
        return {
          audio: item.audio,
          state: 'unavailable',
          message: inaccessible
            ? 'No longer accessible or deleted'
            : 'Could not verify this audio',
        }
      }
    }),
  )
  selected.value = results
  validating.value = false
  return results.every((item) => item.state === 'valid')
}

async function submit(): Promise<void> {
  if (submitting.value || accepted.value) return
  errorMessage.value = ''
  const normalizedTitle = title.value.trim()
  const normalizedPresetId = Number(presetId.value)
  if (!normalizedTitle) {
    errorMessage.value = 'Enter a paper title'
    return
  }
  if (!Number.isInteger(normalizedPresetId) || normalizedPresetId < 1) {
    errorMessage.value = 'Select a paper preset'
    return
  }
  if (selected.value.length === 0) {
    errorMessage.value = 'Select at least one audio'
    return
  }
  if (!(await validateSelections())) {
    errorMessage.value = 'Remove or replace unavailable audio before rendering'
    return
  }
  submitting.value = true
  try {
    const paper = await createPaper({
      title: normalizedTitle,
      presetId: normalizedPresetId,
      audioIds: selected.value.map((item) => item.audio.id),
    })
    accepted.value = await renderPaper(paper.id)
    await refreshJob()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : 'Paper could not be submitted'
  } finally {
    submitting.value = false
  }
}

async function refreshJob(): Promise<void> {
  if (!accepted.value) return
  try {
    job.value = await getJob(accepted.value.jobId)
    errorMessage.value = ''
    if (job.value.status === 'succeeded') {
      stopPolling()
      const audioId =
        job.value.result?.type === 'audio'
          ? job.value.result.id
          : accepted.value.audioId
      await router.push({ name: 'audio', params: { id: audioId } })
      return
    }
    if (job.value.status === 'queued' || job.value.status === 'running') {
      schedulePoll()
    }
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Render progress could not be loaded'
    schedulePoll()
  }
}

async function cancelRendering(): Promise<void> {
  if (!accepted.value || cancelling.value) return
  cancelling.value = true
  errorMessage.value = ''
  try {
    job.value = await cancelJob(accepted.value.jobId)
    stopPolling()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : 'Render could not be cancelled'
  } finally {
    cancelling.value = false
  }
}

function schedulePoll(): void {
  stopPolling()
  pollTimer = window.setTimeout(() => void refreshJob(), 1000)
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function formatMilliseconds(value: number): string {
  if (value < 1000) return `${value} ms`
  return `${value / 1000} s`
}

function formatDuration(value: number | null): string {
  if (value === null) return 'Pending selection'
  const seconds = Math.max(0, Math.round(value))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function statusLabel(status: JobStatus | Audio['status']): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

function statusClass(status: JobStatus): string {
  if (status === 'succeeded') return 'text-success'
  if (status === 'failed' || status === 'cancelled') return 'text-danger'
  if (status === 'running') return 'text-warning'
  return 'text-muted'
}

onMounted(() => {
  void loadOptions()
  void loadCandidates()
})
onUnmounted(stopPolling)
</script>

<template>
  <section aria-labelledby="paper-title" class="min-w-0">
    <div class="flex min-w-0 flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div class="min-w-0">
        <p class="mb-1 text-sm font-medium text-accent">Teacher workspace</p>
        <h1 id="paper-title" class="break-words text-2xl font-semibold">Assemble paper</h1>
      </div>
      <span v-if="!accepted" class="text-sm text-muted">
        {{ selected.length }} selected
      </span>
    </div>

    <p
      v-if="errorMessage"
      role="alert"
      class="border-b border-line bg-surface px-5 py-4 text-sm text-danger"
    >
      {{ errorMessage }}
    </p>

    <div v-if="accepted" class="border-b border-line bg-surface px-5 py-6">
      <div class="flex min-w-0 items-start justify-between gap-5">
        <div class="min-w-0">
          <h2 class="text-base font-semibold">Rendering {{ title.trim() }}</h2>
          <p class="mt-1 text-sm text-muted">Output audio {{ accepted.audioId }}</p>
        </div>
        <span class="shrink-0 text-sm font-medium tabular-nums">{{ job?.progress ?? 0 }}%</span>
      </div>
      <div
        class="mt-5 h-2 overflow-hidden bg-canvas"
        role="progressbar"
        aria-label="Paper rendering progress"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="job?.progress ?? 0"
      >
        <div class="h-full bg-accent" :style="{ width: `${job?.progress ?? 0}%` }" />
      </div>
      <div v-if="job" class="mt-4 flex flex-wrap items-center justify-between gap-4">
        <span class="inline-flex items-center gap-2 text-sm font-medium" :class="statusClass(job.status)">
          <span class="h-2 w-2 bg-current" aria-hidden="true" />
          {{ statusLabel(job.status) }}
        </span>
        <button
          v-if="job.status === 'queued' || job.status === 'running'"
          type="button"
          :disabled="cancelling"
          class="h-9 border border-line px-3 text-sm font-medium text-danger hover:border-danger disabled:opacity-50"
          @click="cancelRendering"
        >
          {{ cancelling ? 'Cancelling' : 'Cancel render' }}
        </button>
      </div>
      <p v-if="job?.errorSummary" class="mt-3 break-words text-sm text-danger">
        {{ job.errorSummary }}
      </p>
    </div>

    <template v-else>
      <div class="grid min-w-0 gap-6 border-b border-line bg-surface px-5 py-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div class="min-w-0">
          <label for="paper-name" class="mb-1 block text-sm font-medium">Paper title</label>
          <input
            id="paper-name"
            v-model="title"
            type="text"
            maxlength="200"
            class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>
        <div class="min-w-0">
          <label for="paper-preset" class="mb-1 block text-sm font-medium">Preset</label>
          <select
            id="paper-preset"
            v-model="presetId"
            :disabled="loadingOptions"
            class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus disabled:opacity-50"
          >
            <option value="" disabled>Select preset</option>
            <option v-for="preset in presets" :key="preset.id" :value="String(preset.id)">
              {{ preset.name }}{{ preset.isBuiltin ? ' (built-in)' : '' }}
            </option>
          </select>
        </div>
      </div>

      <dl
        v-if="selectedPreset"
        class="grid border-b border-line bg-surface sm:grid-cols-3 lg:grid-cols-5"
        aria-label="Preset parameters"
      >
        <div class="border-b border-line px-4 py-4 sm:border-r lg:border-b-0">
          <dt class="text-xs text-muted">Intro</dt>
          <dd class="mt-1 text-sm font-medium">{{ formatMilliseconds(selectedPreset.introSilenceMilliseconds) }}</dd>
        </div>
        <div class="border-b border-line px-4 py-4 sm:border-r lg:border-b-0">
          <dt class="text-xs text-muted">Between items</dt>
          <dd class="mt-1 text-sm font-medium">{{ formatMilliseconds(selectedPreset.interItemSilenceMilliseconds) }}</dd>
        </div>
        <div class="border-b border-line px-4 py-4 lg:border-b-0 lg:border-r">
          <dt class="text-xs text-muted">Repeats</dt>
          <dd class="mt-1 text-sm font-medium">{{ selectedPreset.repeatCount }}</dd>
        </div>
        <div class="border-b border-line px-4 py-4 sm:border-b-0 sm:border-r">
          <dt class="text-xs text-muted">Outro</dt>
          <dd class="mt-1 text-sm font-medium">{{ formatMilliseconds(selectedPreset.outroSilenceMilliseconds) }}</dd>
        </div>
        <div class="px-4 py-4">
          <dt class="text-xs text-muted">Estimated length</dt>
          <dd class="mt-1 text-sm font-medium">{{ formatDuration(estimatedDuration) }}</dd>
        </div>
      </dl>

      <div class="grid min-w-0 gap-8 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.9fr)]">
        <section aria-labelledby="candidate-title" class="min-w-0">
          <div class="mb-4 flex min-w-0 items-end justify-between gap-3">
            <div>
              <h2 id="candidate-title" class="text-base font-semibold">Audio candidates</h2>
              <p class="mt-1 text-sm text-muted">{{ total }} available</p>
            </div>
          </div>
          <AudioSearchBox
            v-model="query"
            :tags="tagCatalog"
            :busy="loadingCandidates"
            @submit="loadCandidates(true)"
          />
          <p v-if="loadingCandidates" class="border-b border-line py-10 text-sm text-muted">
            Loading candidates
          </p>
          <p v-else-if="candidates.length === 0" class="border-b border-line py-10 text-sm text-muted">
            No audio found
          </p>
          <ul v-else class="mt-4 divide-y divide-line border-y border-line bg-surface">
            <li
              v-for="audio in candidates"
              :key="audio.id"
              class="grid min-w-0 gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_8rem] sm:items-center"
            >
              <div class="min-w-0">
                <p class="break-words text-sm font-semibold">{{ audio.title }}</p>
                <p class="mt-1 break-words text-xs text-muted">
                  {{ audio.author.username || audio.author.userId }}
                </p>
                <audio
                  class="mt-3 h-9 w-full"
                  controls
                  preload="none"
                  :src="audioMediaPath(audio.id)"
                ></audio>
              </div>
              <button
                type="button"
                :disabled="selectedIds.has(audio.id) || selected.length >= 100"
                class="inline-flex h-9 items-center justify-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink disabled:opacity-45"
                @click="addAudio(audio)"
              >
                <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
                </svg>
                {{ selectedIds.has(audio.id) ? 'Selected' : 'Add' }}
              </button>
            </li>
          </ul>
          <nav
            v-if="!loadingCandidates && totalPages > 1"
            class="flex items-center justify-between gap-3 border-b border-line py-4"
            aria-label="Candidate pages"
          >
            <button
              type="button"
              :disabled="page === 1"
              class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium disabled:opacity-45"
              @click="movePage(page - 1)"
            >
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                <path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" />
              </svg>
              Previous
            </button>
            <span class="text-sm tabular-nums text-muted">{{ page }} / {{ totalPages }}</span>
            <button
              type="button"
              :disabled="page === totalPages"
              class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium disabled:opacity-45"
              @click="movePage(page + 1)"
            >
              Next
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
              </svg>
            </button>
          </nav>
        </section>

        <section aria-labelledby="selected-title" class="min-w-0">
          <div class="mb-4 flex min-w-0 items-end justify-between gap-3">
            <div>
              <h2 id="selected-title" class="text-base font-semibold">Selected order</h2>
              <p class="mt-1 text-sm text-muted">{{ selected.length }} items</p>
            </div>
            <button
              v-if="selected.length > 0"
              type="button"
              :disabled="validating || submitting"
              class="inline-flex h-9 shrink-0 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink disabled:opacity-50"
              @click="validateSelections"
            >
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                <path d="M20 12a8 8 0 1 1-2.34-5.66L20 8" stroke="currentColor" stroke-width="2" />
                <path d="M20 4v4h-4" stroke="currentColor" stroke-width="2" />
              </svg>
              {{ validating ? 'Checking' : 'Check' }}
            </button>
          </div>
          <p v-if="selected.length === 0" class="border-y border-line bg-surface px-4 py-10 text-sm text-muted">
            No audio selected
          </p>
          <PaperSelectedAudioList
            v-else
            :items="selected"
            :disabled="validating || submitting"
            @move="moveAudio"
            @remove="removeAudio"
          />
          <p v-if="invalidSelection" class="mt-3 text-sm text-danger">
            Unavailable items cannot be rendered.
          </p>
        </section>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-4 border-t border-line bg-surface px-5 py-5">
        <p class="text-sm text-muted">Output visibility: Private</p>
        <button
          type="button"
          :disabled="submitting || validating || loadingOptions"
          class="h-10 bg-ink px-5 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
          @click="submit"
        >
          {{ submitting || validating ? 'Checking and submitting' : 'Render paper' }}
        </button>
      </div>
    </template>
  </section>
</template>
