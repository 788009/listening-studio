<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  createAssembly,
  createAssemblyPreview,
  createAssemblyTemplate,
  deleteAssemblyPreview,
  deleteAssemblyTemplate,
  listAssemblyTemplates,
  assemblyPreviewMediaPath,
  type AssemblySegmentInput,
  type AssemblySegmentType,
  type AssemblyTemplate,
} from '@/api/assemblies'
import {
  audioMediaPath,
  createAudioTag,
  getAudio,
  listAudios,
  listAudioTags,
  type Audio,
  type AudioQuestion,
  type AudioTag,
  type ResourceVisibility,
} from '@/api/audios'
import { ApiError } from '@/api/errors'
import { cancelJob, getJob, type Job } from '@/api/jobs'
import type { TagTranslation } from '@/api/voices'
import AudioSearchBox from '@/components/AudioSearchBox.vue'
import AudioQuestionsDisplay from '@/components/AudioQuestionsDisplay.vue'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const PAGE_SIZE = 10
let nextKey = 1
type CreationTagType = 'topic' | 'category'
const tagGroups: { label: string; type: CreationTagType }[] = [
  { label: 'Topics', type: 'topic' },
  { label: 'Categories', type: 'category' },
]

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
const creatingTagType = ref<CreationTagType | null>(null)
const tagDialogType = ref<CreationTagType | null>(null)
const tagDialogInitialEnglishValue = ref('')
const tagDialogError = ref('')
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
const previewPlayer = ref<HTMLAudioElement | null>(null)
const previewJob = ref<Job | null>(null)
const previewJobId = ref<number | null>(null)
const previewMediaUrl = ref('')
const previewBusy = ref(false)
const previewPlaying = ref(false)
const activePreview = ref<{ segmentKey: number; fromHere: boolean } | null>(null)
let publishPollTimer: number | undefined
let previewPollTimer: number | undefined
let previewRequestVersion = 0

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const tagCatalog = computed(() => {
  const catalog = new Map<number, AudioTag>()
  for (const tag of tags.value) catalog.set(tag.id, tag)
  for (const audio of candidates.value) for (const tag of audio.tags) catalog.set(tag.id, tag)
  return [...catalog.values()]
})
const fullPaperTagId = computed(
  () =>
    tags.value.find(
      (tag) => tag.type === 'category' && tag.englishValue === 'full_paper',
    )?.id ?? null,
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
const previewText = computed(() =>
  segments.value
    .filter((segment) => segment.audio && segment.includeText)
    .map((segment) => segment.audio!.text)
    .join('\n\n'),
)
const previewQuestions = computed<AudioQuestion[]>(() => {
  let previewId = -1
  return segments.value.flatMap((segment) =>
    (segment.audio?.questions ?? []).map((question) => ({
      ...question,
      id: previewId--,
    })),
  )
})
const segmentFingerprint = computed(() =>
  JSON.stringify(segments.value.map(segmentInput)),
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

function canPlaySegment(segment: DraftSegment, index: number): boolean {
  if (segment.type === 'silence') return false
  if (segment.type === 'audio') return Boolean(segment.audioId)
  if (segment.type === 'placeholder') return Boolean(segment.audioId)
  const next = segments.value[index + 1]
  return next?.type === 'placeholder' && Boolean(next.audioId)
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

async function playPreview(index: number, fromHere: boolean): Promise<void> {
  const segment = segments.value[index]
  if (!segment || !canPlaySegment(segment, index)) return
  const samePreview =
    activePreview.value?.segmentKey === segment.key &&
    activePreview.value.fromHere === fromHere
  if (samePreview && previewMediaUrl.value) {
    const player = previewPlayer.value
    if (!player) return
    if (!player.paused) {
      player.pause()
      player.currentTime = 0
      return
    }
    try {
      await player.play()
    } catch {
      errorMessage.value = t('Use the audio controls to start playback')
    }
    return
  }
  if (previewBusy.value) return

  const requestVersion = ++previewRequestVersion
  previewBusy.value = true
  await discardPreview(false, true)
  if (requestVersion !== previewRequestVersion) return
  activePreview.value = { segmentKey: segment.key, fromHere }
  errorMessage.value = ''
  try {
    const acceptedPreview = await createAssemblyPreview({
      segments: segments.value.map(segmentInput),
      startIndex: index,
      endIndex: fromHere ? undefined : index,
    })
    if (requestVersion !== previewRequestVersion) {
      void deleteAssemblyPreview(acceptedPreview.jobId).catch(() => undefined)
      return
    }
    previewJobId.value = acceptedPreview.jobId
    await refreshPreviewJob(requestVersion)
  } catch (error) {
    if (requestVersion === previewRequestVersion) {
      previewBusy.value = false
      errorMessage.value =
        error instanceof ApiError ? error.message : t('Playback preview could not be created')
      activePreview.value = null
    }
  }
}

async function refreshPreviewJob(requestVersion: number): Promise<void> {
  const jobId = previewJobId.value
  if (jobId === null || requestVersion !== previewRequestVersion) return
  try {
    previewJob.value = await getJob(jobId)
    if (requestVersion !== previewRequestVersion) return
    if (previewJob.value.status === 'succeeded') {
      previewBusy.value = false
      previewMediaUrl.value = assemblyPreviewMediaPath(jobId)
      await nextTick()
      previewPlayer.value?.load()
      try {
        await previewPlayer.value?.play()
      } catch {
        errorMessage.value = t('Use the audio controls to start playback')
      }
      return
    }
    if (previewJob.value.status === 'queued' || previewJob.value.status === 'running') {
      previewPollTimer = window.setTimeout(
        () => void refreshPreviewJob(requestVersion),
        500,
      )
      return
    }
    previewBusy.value = false
    activePreview.value = null
    errorMessage.value =
      previewJob.value.errorSummary || t('Playback preview could not be created')
  } catch (error) {
    previewBusy.value = false
    activePreview.value = null
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Playback status could not be loaded')
  }
}

async function discardPreview(
  invalidate = true,
  preserveBusy = false,
): Promise<void> {
  if (invalidate) previewRequestVersion += 1
  if (previewPollTimer !== undefined) window.clearTimeout(previewPollTimer)
  previewPollTimer = undefined
  previewPlayer.value?.pause()
  previewPlaying.value = false
  previewMediaUrl.value = ''
  previewJob.value = null
  if (!preserveBusy) previewBusy.value = false
  activePreview.value = null
  const jobId = previewJobId.value
  previewJobId.value = null
  if (jobId !== null) {
    await deleteAssemblyPreview(jobId).catch(() => undefined)
  }
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
    await discardPreview()
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

function selectTag(tagId: number): void {
  if (!selectedTagIds.value.includes(tagId)) {
    selectedTagIds.value = [...selectedTagIds.value, tagId]
  }
}

function removeTag(tagId: number): void {
  if (tagId === fullPaperTagId.value) return
  selectedTagIds.value = selectedTagIds.value.filter((id) => id !== tagId)
}

function openTagDialog(type: CreationTagType, query: string): void {
  tagDialogType.value = type
  tagDialogInitialEnglishValue.value = query
  tagDialogError.value = ''
}

function closeTagDialog(): void {
  if (creatingTagType.value !== null) return
  tagDialogType.value = null
  tagDialogInitialEnglishValue.value = ''
  tagDialogError.value = ''
}

async function createAndAddTag(input: {
  englishValue: string
  translations: TagTranslation[]
}): Promise<void> {
  if (tagDialogType.value === null || creatingTagType.value !== null) return
  const type = tagDialogType.value
  creatingTagType.value = type
  tagDialogError.value = ''
  try {
    const tag = await createAudioTag({ type, ...input })
    tags.value = [...tags.value, tag]
    selectTag(tag.id)
    tagDialogType.value = null
    tagDialogInitialEnglishValue.value = ''
  } catch (error) {
    tagDialogError.value =
      error instanceof ApiError ? error.message : t('Tag could not be created')
  } finally {
    creatingTagType.value = null
  }
}

async function refreshJob(): Promise<void> {
  if (!accepted.value) return
  try {
    job.value = await getJob(accepted.value.jobId)
    if (job.value.status === 'succeeded') {
      stopPublishPolling()
      await router.push({ name: 'audio', params: { id: accepted.value.audioId } })
    } else if (job.value.status === 'queued' || job.value.status === 'running') {
      stopPublishPolling()
      publishPollTimer = window.setTimeout(() => void refreshJob(), 1000)
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Render progress could not be loaded')
  }
}

async function cancel(): Promise<void> {
  if (!accepted.value) return
  job.value = await cancelJob(accepted.value.jobId)
  stopPublishPolling()
}

function stopPublishPolling(): void {
  if (publishPollTimer !== undefined) window.clearTimeout(publishPollTimer)
  publishPollTimer = undefined
}

function duration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds))
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

onMounted(() => {
  void Promise.all([loadOptions(), loadPage()])
})
watch(segmentFingerprint, () => void discardPreview())
onUnmounted(() => {
  stopPublishPolling()
  void discardPreview()
})
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

          <div v-if="previewBusy || previewMediaUrl" class="mb-4 border-y border-line py-3">
            <div class="flex items-center justify-between gap-3 text-sm">
              <span>{{ t('Assembly playback preview') }}</span>
              <div v-if="previewBusy" class="flex items-center gap-3">
                <span class="text-muted">{{ t('Preparing playback') }} {{ previewJob?.progress ?? 0 }}%</span>
                <button type="button" class="text-danger" @click="discardPreview()">{{ t('Cancel preview') }}</button>
              </div>
            </div>
            <audio
              v-if="previewMediaUrl"
              ref="previewPlayer"
              class="mt-3 h-9 w-full"
              controls
              preload="metadata"
              :src="previewMediaUrl"
              @play="previewPlaying = true"
              @pause="previewPlaying = false"
              @ended="previewPlaying = false"
            />
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
                <div v-if="segment.type !== 'silence'" class="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    :disabled="previewBusy || !canPlaySegment(segment, index)"
                    class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm disabled:opacity-40"
                    @click="playPreview(index, false)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" /></svg>
                    {{ activePreview?.segmentKey === segment.key && !activePreview.fromHere && previewBusy ? t('Preparing playback') : activePreview?.segmentKey === segment.key && !activePreview.fromHere && previewPlaying ? t('Stop') : t('Play') }}
                  </button>
                  <button
                    type="button"
                    :disabled="previewBusy || !canPlaySegment(segment, index)"
                    class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm disabled:opacity-40"
                    @click="playPreview(index, true)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 5v14M9 5l10 7-10 7V5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" /></svg>
                    {{ activePreview?.segmentKey === segment.key && activePreview.fromHere && previewBusy ? t('Preparing playback') : activePreview?.segmentKey === segment.key && activePreview.fromHere && previewPlaying ? t('Stop') : t('Play from here') }}
                  </button>
                </div>
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

      <section aria-labelledby="assembly-preview-title" class="border-t border-line py-6">
        <h2 id="assembly-preview-title" class="text-base font-semibold">{{ t('Preview') }}</h2>
        <div class="mt-5 grid min-w-0 gap-8 lg:grid-cols-2">
          <div class="min-w-0">
            <h3 class="text-sm font-semibold">{{ t('Text') }}</h3>
            <p v-if="previewText" class="mt-4 whitespace-pre-wrap break-words text-sm leading-7">{{ previewText }}</p>
            <p v-else class="mt-4 text-sm text-muted">{{ t('No text included') }}</p>
          </div>
          <div class="min-w-0">
            <h3 class="text-sm font-semibold">{{ t('Questions') }}</h3>
            <AudioQuestionsDisplay v-if="previewQuestions.length" class="mt-4" :questions="previewQuestions" />
            <p v-else class="mt-4 text-sm text-muted">{{ t('No questions') }}</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="paper-tags-title" class="border-y border-line py-5">
        <h2 id="paper-tags-title" class="text-base font-semibold">{{ t('Tags') }}</h2>
        <div class="mt-5 grid min-w-0 gap-5 sm:grid-cols-2">
          <ResourceTagPicker
            v-for="group in tagGroups"
            :key="group.type"
            :label="group.label"
            :type="group.type"
            :tags="tags"
            :selected-ids="selectedTagIds"
            :locked-ids="group.type === 'category' && fullPaperTagId ? [fullPaperTagId] : []"
            @select="selectTag"
            @remove="removeTag"
            @create="openTagDialog(group.type, $event)"
          />
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

    <TagCreationDialog
      :open="tagDialogType !== null"
      :type="tagDialogType"
      :initial-english-value="tagDialogInitialEnglishValue"
      :busy="creatingTagType !== null"
      :error-message="tagDialogError"
      @close="closeTagDialog"
      @submit="createAndAddTag"
    />
  </section>
</template>
