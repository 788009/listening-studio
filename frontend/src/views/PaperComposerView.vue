<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createAssembly,
  createAssemblyTemplate,
  deleteAssemblyTemplate,
  listAssemblyTemplates,
  type AssemblySegmentInput,
  type AssemblySegmentType,
  type AssemblyTemplate,
} from '@/api/assemblies'
import {
  audioMediaPath,
  getAudio,
  listAudios,
  listAudioTags,
  type Audio,
  type AudioTag,
  type ResourceVisibility,
} from '@/api/audios'
import { ApiError } from '@/api/errors'
import { cancelJob, getJob, type Job } from '@/api/jobs'
import AudioSearchBox from '@/components/AudioSearchBox.vue'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const PAGE_SIZE = 10
let nextKey = 1

interface DraftSegment extends AssemblySegmentInput {
  key: number
  audio?: Audio
}

const router = useRouter()
const auth = useAuthStore()
const { locale, t } = useI18n()
const title = ref('')
const visibility = ref<ResourceVisibility>('public')
const templates = ref<AssemblyTemplate[]>([])
const templateId = ref('')
const templateTitle = ref('')
const segments = ref<DraftSegment[]>([])
const candidates = ref<Audio[]>([])
const tags = ref<AudioTag[]>([])
const selectedTagIds = ref<number[]>([])
const query = ref('')
const page = ref(1)
const total = ref(0)
const activePlaceholder = ref<number | null>(null)
const loading = ref(true)
const submitting = ref(false)
const savingTemplate = ref(false)
const errorMessage = ref('')
const accepted = ref<{ audioId: number; jobId: number } | null>(null)
const job = ref<Job | null>(null)
let pollTimer: number | undefined

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const tagCatalog = computed(() => {
  const catalog = new Map<number, AudioTag>()
  for (const tag of tags.value) catalog.set(tag.id, tag)
  for (const audio of candidates.value) for (const tag of audio.tags) catalog.set(tag.id, tag)
  return [...catalog.values()]
})
const editableTags = computed(() =>
  tags.value.filter((tag) => tag.type === 'topic' || tag.type === 'category'),
)
const estimatedSeconds = computed(() =>
  segments.value.reduce((totalSeconds, segment) => {
    if (segment.type === 'silence') {
      return totalSeconds + (segment.silenceMilliseconds ?? 0) / 1000
    }
    if (!segment.audio?.durationSeconds) return totalSeconds
    return (
      totalSeconds +
      segment.audio.durationSeconds * (segment.repeatCount ?? 1) +
      ((segment.repeatIntervalMilliseconds ?? 0) / 1000) *
        Math.max(0, (segment.repeatCount ?? 1) - 1)
    )
  }, 0),
)

function draft(type: AssemblySegmentType, values: Partial<DraftSegment> = {}): DraftSegment {
  return {
    key: nextKey++,
    type,
    repeatCount: 1,
    repeatIntervalMilliseconds: 3000,
    includeText: true,
    includeTopic: true,
    silenceMilliseconds: 0,
    ...values,
  }
}

async function loadPage(reset = false): Promise<void> {
  if (reset) page.value = 1
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
    errorMessage.value = error instanceof ApiError ? error.message : t('Audio candidates could not be loaded')
  }
}

async function loadOptions(): Promise<void> {
  loading.value = true
  try {
    ;[templates.value, tags.value] = await Promise.all([
      listAssemblyTemplates(),
      listAudioTags(locale.value),
    ])
    const fullPaper = tags.value.find(
      (tag) => tag.type === 'category' && tag.englishValue === 'full_paper',
    )
    if (fullPaper) selectedTagIds.value = [fullPaper.id]
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Paper options could not be loaded')
  } finally {
    loading.value = false
  }
}

async function applyTemplate(): Promise<void> {
  const template = templates.value.find((item) => String(item.id) === templateId.value)
  if (!template) return
  errorMessage.value = ''
  const next: DraftSegment[] = []
  for (const item of template.segments) {
    let audio: Audio | undefined
    if (item.audioId) {
      try {
        audio = await getAudio(item.audioId, locale.value)
      } catch {
        audio = undefined
      }
    }
    next.push(draft(item.type, { ...item, audio }))
  }
  segments.value = next
  resetPrefilledTags()
  for (const segment of next) {
    if (segment.audio && segment.includeTopic) addAudioTopics(segment.audio)
  }
}

function addAudio(audio: Audio): void {
  if (activePlaceholder.value !== null) {
    const segment = segments.value[activePlaceholder.value]
    if (segment?.type === 'placeholder') {
      segment.audio = audio
      segment.audioId = audio.id
      if (segment.includeTopic) addAudioTopics(audio)
      activePlaceholder.value = null
      return
    }
  }
  segments.value.push(draft('audio', { audio, audioId: audio.id }))
  addAudioTopics(audio)
}

function addAudioTopics(audio: Audio): void {
  const topicIds = audio.tags.filter((tag) => tag.type === 'topic').map((tag) => tag.id)
  selectedTagIds.value = [...new Set([...selectedTagIds.value, ...topicIds])]
}

function resetPrefilledTags(): void {
  selectedTagIds.value = selectedTagIds.value.filter((id) => {
    const tag = tags.value.find((item) => item.id === id)
    return tag?.type === 'category' || tag === undefined
  })
}

function setSegmentTopic(segment: DraftSegment, selected: boolean): void {
  segment.includeTopic = selected
  if (selected && segment.audio) {
    addAudioTopics(segment.audio)
    return
  }
  if (!segment.audio) return
  const removableIds = new Set(
    segment.audio.tags.filter((tag) => tag.type === 'topic').map((tag) => tag.id),
  )
  for (const other of segments.value) {
    if (other.key === segment.key || !other.includeTopic || !other.audio) continue
    for (const tag of other.audio.tags) removableIds.delete(tag.id)
  }
  selectedTagIds.value = selectedTagIds.value.filter((id) => !removableIds.has(id))
}

function addSilence(): void {
  segments.value.push(draft('silence', { silenceMilliseconds: 5000 }))
}

function seconds(milliseconds: number | undefined): number {
  return (milliseconds ?? 0) / 1000
}

function millisecondsFromInput(event: Event): number {
  const value = (event.target as HTMLInputElement).valueAsNumber
  return Number.isFinite(value) ? Math.round(value * 1000) : 0
}

function addPlaceholder(): void {
  segments.value.push(draft('placeholder', { suggestedQuery: '' }))
}

function addSmart(): void {
  segments.value.push(draft('smart', { includeText: false, includeTopic: false }))
  addPlaceholder()
}

function selectPlaceholder(index: number): void {
  activePlaceholder.value = index
  query.value = segments.value[index]?.suggestedQuery ?? ''
  void loadPage(true)
}

function move(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= segments.value.length) return
  const next = [...segments.value]
  const [item] = next.splice(index, 1)
  if (!item) return
  next.splice(target, 0, item)
  segments.value = next
  activePlaceholder.value = null
}

function remove(index: number): void {
  segments.value.splice(index, 1)
  activePlaceholder.value = null
}

function segmentInput(segment: DraftSegment): AssemblySegmentInput {
  return {
    type: segment.type,
    audioId: segment.audioId,
    suggestedQuery: segment.suggestedQuery || undefined,
    silenceMilliseconds: segment.type === 'silence' ? segment.silenceMilliseconds : 0,
    repeatCount: segment.repeatCount,
    repeatIntervalMilliseconds: segment.repeatIntervalMilliseconds,
    includeText: segment.includeText,
    includeTopic: segment.includeTopic,
  }
}

function validate(): string | null {
  if (!title.value.trim()) return t('Enter a paper title')
  if (segments.value.length === 0) return t('Add at least one segment')
  for (let index = 0; index < segments.value.length; index += 1) {
    const item = segments.value[index]!
    if ((item.type === 'audio' || item.type === 'placeholder') && !item.audioId) {
      return t('Fill every placeholder before publishing')
    }
    if (item.type === 'smart' && segments.value[index + 1]?.type !== 'placeholder') {
      return t('Every smart segment must be followed by a placeholder')
    }
  }
  return null
}

async function submit(): Promise<void> {
  const validationError = validate()
  if (validationError || submitting.value) {
    errorMessage.value = validationError ?? ''
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    accepted.value = await createAssembly({
      title: title.value.trim(),
      templateId: templateId.value ? Number(templateId.value) : undefined,
      segments: segments.value.map(segmentInput),
      tagIds: selectedTagIds.value,
      visibility: visibility.value,
    })
    await refreshJob()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Paper could not be submitted')
  } finally {
    submitting.value = false
  }
}

async function saveTemplate(): Promise<void> {
  if (!auth.isAdmin || savingTemplate.value || !templateTitle.value.trim()) return
  savingTemplate.value = true
  errorMessage.value = ''
  try {
    const created = await createAssemblyTemplate({
      title: templateTitle.value.trim(),
      segments: segments.value.map((segment) => {
        const input = segmentInput(segment)
        if (input.type === 'placeholder') delete input.audioId
        return input
      }),
    })
    templates.value = [created, ...templates.value]
    templateId.value = String(created.id)
    templateTitle.value = ''
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Template could not be saved')
  } finally {
    savingTemplate.value = false
  }
}

async function removeTemplate(): Promise<void> {
  const id = Number(templateId.value)
  if (!auth.isAdmin || !Number.isInteger(id)) return
  await deleteAssemblyTemplate(id)
  templates.value = templates.value.filter((item) => item.id !== id)
  templateId.value = ''
}

function toggleTag(tag: AudioTag): void {
  if (tag.type === 'category' && tag.englishValue === 'full_paper') return
  selectedTagIds.value = selectedTagIds.value.includes(tag.id)
    ? selectedTagIds.value.filter((id) => id !== tag.id)
    : [...selectedTagIds.value, tag.id]
}

async function refreshJob(): Promise<void> {
  if (!accepted.value) return
  try {
    job.value = await getJob(accepted.value.jobId)
    if (job.value.status === 'succeeded') {
      stopPolling()
      await router.push({ name: 'audio', params: { id: accepted.value.audioId } })
    } else if (job.value.status === 'queued' || job.value.status === 'running') {
      stopPolling()
      pollTimer = window.setTimeout(() => void refreshJob(), 1000)
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Render progress could not be loaded')
  }
}

async function cancel(): Promise<void> {
  if (!accepted.value) return
  job.value = await cancelJob(accepted.value.jobId)
  stopPolling()
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function duration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds))
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

onMounted(() => {
  void Promise.all([loadOptions(), loadPage()])
})
onUnmounted(stopPolling)
</script>

<template>
  <section aria-labelledby="paper-title" class="page-shell pb-10">
    <div class="page-heading">
      <div class="min-w-0">
        <p class="eyebrow">{{ t('Teacher workspace') }}</p>
        <h1 id="paper-title" class="break-words text-3xl font-semibold">{{ t('Assemble paper') }}</h1>
      </div>
      <span class="text-sm tabular-nums text-muted">{{ t('{count} segments', { count: segments.length }) }}</span>
    </div>

    <p v-if="errorMessage" role="alert" class="mt-5 border-y border-danger/30 py-3 text-sm text-danger">{{ errorMessage }}</p>

    <div v-if="accepted" class="mt-7 border-y border-line py-6">
      <div class="flex items-center justify-between gap-4">
        <h2 class="text-base font-semibold">{{ t('Rendering {title}', { title }) }}</h2>
        <span class="text-sm tabular-nums">{{ job?.progress ?? 0 }}%</span>
      </div>
      <div class="mt-4 h-2 bg-canvas" role="progressbar" :aria-valuenow="job?.progress ?? 0" aria-valuemin="0" aria-valuemax="100">
        <div class="h-full bg-accent" :style="{ width: `${job?.progress ?? 0}%` }" />
      </div>
      <button v-if="job?.status === 'queued' || job?.status === 'running'" type="button" class="mt-4 text-sm text-danger" @click="cancel">{{ t('Cancel render') }}</button>
    </div>

    <template v-else>
      <div class="mt-7 grid gap-5 border-y border-line py-5 lg:grid-cols-[minmax(0,1fr)_18rem_10rem]">
        <label class="min-w-0 text-sm font-medium">
          {{ t('Paper title') }}
          <input v-model="title" maxlength="200" class="mt-2 h-10 w-full border border-line px-3 font-normal focus:border-accent focus:outline-none" />
        </label>
        <label class="min-w-0 text-sm font-medium">
          {{ t('Template') }}
          <select v-model="templateId" class="mt-2 h-10 w-full border border-line bg-surface px-3 font-normal" @change="applyTemplate">
            <option value="">{{ t('No template') }}</option>
            <option v-for="item in templates" :key="item.id" :value="String(item.id)">{{ item.title }}</option>
          </select>
        </label>
        <label class="min-w-0 text-sm font-medium">
          {{ t('Visibility') }}
          <select v-model="visibility" class="mt-2 h-10 w-full border border-line bg-surface px-3 font-normal">
            <option value="public">{{ t('Public') }}</option>
            <option value="private">{{ t('Private') }}</option>
          </select>
        </label>
      </div>

      <div class="grid min-w-0 gap-8 py-7 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.35fr)]">
        <section aria-labelledby="audio-source-title" class="min-w-0">
          <div class="mb-4 flex items-end justify-between gap-3">
            <div>
              <h2 id="audio-source-title" class="text-base font-semibold">{{ t('Audio library') }}</h2>
              <p class="mt-1 text-sm text-muted">{{ t('{count} available', { count: total }) }}</p>
            </div>
            <span v-if="activePlaceholder !== null" class="text-xs font-medium text-accent">{{ t('Filling placeholder') }}</span>
          </div>
          <AudioSearchBox v-model="query" :tags="tagCatalog" :busy="loading" @submit="loadPage(true)" />
          <ul class="mt-4 divide-y divide-line border-y border-line">
            <li v-for="audio in candidates" :key="audio.id" class="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div class="min-w-0">
                <p class="break-words text-sm font-semibold">{{ audio.title }}</p>
                <p class="mt-1 text-xs text-muted">{{ audio.questions?.length ?? 0 }} {{ t('Questions') }} · {{ audio.durationSeconds === null ? '' : duration(audio.durationSeconds) }}</p>
                <audio class="mt-2 h-8 w-full" controls preload="none" :src="audioMediaPath(audio.id)" />
              </div>
              <button type="button" class="h-9 border border-line px-3 text-sm font-medium hover:border-ink" @click="addAudio(audio)">{{ activePlaceholder === null ? t('Add') : t('Select') }}</button>
            </li>
          </ul>
          <nav v-if="totalPages > 1" class="mt-4 flex items-center justify-between text-sm">
            <button type="button" :disabled="page === 1" class="h-9 border border-line px-3 disabled:opacity-40" @click="page -= 1; loadPage()">{{ t('Previous') }}</button>
            <span class="tabular-nums text-muted">{{ page }} / {{ totalPages }}</span>
            <button type="button" :disabled="page === totalPages" class="h-9 border border-line px-3 disabled:opacity-40" @click="page += 1; loadPage()">{{ t('Next') }}</button>
          </nav>
        </section>

        <section aria-labelledby="segments-title" class="min-w-0">
          <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="segments-title" class="text-base font-semibold">{{ t('Assembly segments') }}</h2>
              <p class="mt-1 text-sm text-muted">{{ t('Estimated length') }} {{ duration(estimatedSeconds) }}</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button type="button" class="h-9 border border-line px-3 text-sm" @click="addSilence">{{ t('Add silence') }}</button>
              <button v-if="auth.isAdmin" type="button" class="h-9 border border-line px-3 text-sm" @click="addPlaceholder">{{ t('Add placeholder') }}</button>
              <button v-if="auth.isAdmin" type="button" class="h-9 border border-line px-3 text-sm" @click="addSmart">{{ t('Add smart segment') }}</button>
            </div>
          </div>

          <p v-if="segments.length === 0" class="border-y border-line py-10 text-sm text-muted">{{ t('No segments yet') }}</p>
          <ol v-else class="divide-y divide-line border-y border-line">
            <li v-for="(segment, index) in segments" :key="segment.key" class="grid min-w-0 gap-4 py-4 sm:grid-cols-[2rem_minmax(0,1fr)_5.5rem]">
              <span class="pt-1 text-sm tabular-nums text-muted">{{ index + 1 }}</span>
              <div class="min-w-0">
                <template v-if="segment.type === 'silence'">
                  <p class="text-sm font-semibold">{{ t('Silence') }}</p>
                  <label class="mt-3 block text-xs text-muted">{{ t('Duration seconds') }}
                    <input :value="seconds(segment.silenceMilliseconds)" type="number" min="0" max="60" step="0.1" class="mt-1 h-9 w-36 border border-line px-2 text-sm text-ink" @input="segment.silenceMilliseconds = millisecondsFromInput($event)" />
                  </label>
                </template>
                <template v-else-if="segment.type === 'smart'">
                  <p class="text-sm font-semibold">{{ t('Smart question-number audio') }}</p>
                  <p class="mt-1 text-xs text-muted">{{ t('Resolved when the paper is submitted') }}</p>
                </template>
                <template v-else>
                  <div class="flex flex-wrap items-baseline gap-2">
                    <p class="break-words text-sm font-semibold">{{ segment.audio?.title || t('Unfilled placeholder') }}</p>
                    <span v-if="segment.type === 'placeholder'" class="text-xs text-accent">{{ t('Placeholder') }}</span>
                  </div>
                  <label v-if="segment.type === 'placeholder' && !segment.audio" class="mt-3 block text-xs text-muted">{{ t('Suggested search') }}
                    <input v-model="segment.suggestedQuery" maxlength="1024" class="mt-1 h-9 w-full border border-line px-2 text-sm text-ink" />
                  </label>
                  <button v-if="segment.type === 'placeholder'" type="button" class="mt-3 text-sm font-medium text-accent" @click="selectPlaceholder(index)">{{ t('Choose audio') }}</button>
                  <div class="mt-3 grid gap-3 sm:grid-cols-2">
                    <label class="text-xs text-muted">{{ t('Repeat count') }}
                      <input v-model.number="segment.repeatCount" type="number" min="1" max="10" class="mt-1 h-9 w-full border border-line px-2 text-sm text-ink" />
                    </label>
                    <label class="text-xs text-muted">{{ t('Repeat interval seconds') }}
                      <input :value="seconds(segment.repeatIntervalMilliseconds)" type="number" min="0" max="60" step="0.1" class="mt-1 h-9 w-full border border-line px-2 text-sm text-ink" @input="segment.repeatIntervalMilliseconds = millisecondsFromInput($event)" />
                    </label>
                  </div>
                  <div class="mt-3 flex flex-wrap gap-5 text-sm">
                    <label class="inline-flex items-center gap-2"><input v-model="segment.includeText" type="checkbox" />{{ t('Include text') }}</label>
                    <label class="inline-flex items-center gap-2"><input :checked="segment.includeTopic" type="checkbox" @change="setSegmentTopic(segment, ($event.target as HTMLInputElement).checked)" />{{ t('Include topic') }}</label>
                  </div>
                </template>
              </div>
              <div class="flex justify-end gap-1">
                <button type="button" :disabled="index === 0" class="flex h-8 w-7 items-center justify-center text-muted disabled:opacity-30" :title="t('Move up')" @click="move(index, -1)"><svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m6 15 6-6 6 6" stroke="currentColor" stroke-width="2" /></svg></button>
                <button type="button" :disabled="index === segments.length - 1" class="flex h-8 w-7 items-center justify-center text-muted disabled:opacity-30" :title="t('Move down')" @click="move(index, 1)"><svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" /></svg></button>
                <button type="button" class="flex h-8 w-7 items-center justify-center text-danger" :title="t('Remove')" @click="remove(index)"><svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 12h14" stroke="currentColor" stroke-width="2" /></svg></button>
              </div>
            </li>
          </ol>
        </section>
      </div>

      <section aria-labelledby="paper-tags-title" class="border-y border-line py-5">
        <h2 id="paper-tags-title" class="text-base font-semibold">{{ t('Final tags') }}</h2>
        <div class="mt-4 flex flex-wrap gap-2">
          <label v-for="tag in editableTags" :key="tag.id" class="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm" :class="selectedTagIds.includes(tag.id) ? 'border-accent bg-accent-soft' : ''">
            <input type="checkbox" :checked="selectedTagIds.includes(tag.id)" :disabled="tag.type === 'category' && tag.englishValue === 'full_paper'" @change="toggleTag(tag)" />
            {{ tag.displayValue.replace(/_/g, ' ') }}
          </label>
        </div>
      </section>

      <section v-if="auth.isAdmin" aria-labelledby="template-admin-title" class="mt-7 border-y border-line py-5">
        <h2 id="template-admin-title" class="text-base font-semibold">{{ t('Template management') }}</h2>
        <div class="mt-4 flex flex-wrap gap-3">
          <input v-model="templateTitle" maxlength="200" :placeholder="t('Template title')" class="h-10 min-w-64 flex-1 border border-line px-3 text-sm" />
          <button type="button" :disabled="savingTemplate || !templateTitle.trim() || segments.length === 0" class="h-10 bg-ink px-4 text-sm font-medium text-white disabled:opacity-40" @click="saveTemplate">{{ t('Save current segments as template') }}</button>
          <button v-if="templateId" type="button" class="h-10 border border-line px-4 text-sm text-danger" @click="removeTemplate">{{ t('Delete selected template') }}</button>
        </div>
      </section>

      <div class="mt-7 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-5">
        <p class="text-sm text-muted">{{ t('Questions are included once even when audio repeats') }}</p>
        <button type="button" :disabled="submitting || loading" class="h-10 bg-ink px-5 text-sm font-medium text-white disabled:opacity-40" @click="submit">{{ submitting ? t('Submitting') : t('Assemble and publish') }}</button>
      </div>
    </template>
  </section>
</template>
