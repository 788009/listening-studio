<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, RouterLink, useRoute } from 'vue-router'

import {
  audioPreviewMediaPath,
  createAudioPreview,
  createAudioTag,
  deleteAudioPreview,
  listAudioCreationTags,
  publishAudioFromPreviews,
  type AudioTag,
  type AudioPreviewInput,
  type ResourceVisibility,
} from '@/api/audios'
import { getJob, type JobStatus } from '@/api/jobs'
import { listVoices, type Voice } from '@/api/voices'
import { ApiError } from '@/api/errors'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import DialogueTurnsEditor from '@/components/DialogueTurnsEditor.vue'
import SpeakerDefinitionsEditor from '@/components/SpeakerDefinitionsEditor.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import type {
  DialogueTurnDraft,
  DialogueTurnPreview,
  SpeakerDraft,
} from '@/components/dialogueTurnTypes'
import type { TagTranslation } from '@/api/voices'
import { useI18n } from '@/i18n'

type CreationTagType = 'topic' | 'category'

const route = useRoute()
const { locale, t } = useI18n()
const title = ref('')
const speakers = ref<SpeakerDraft[]>([])
const turns = ref<DialogueTurnDraft[]>([])
const visibility = ref<ResourceVisibility>('private')
const selectedTagIds = ref<number[]>([])
const voices = ref<Voice[]>([])
const tags = ref<AudioTag[]>([])
const creatingTagType = ref<CreationTagType | null>(null)
const tagDialogType = ref<CreationTagType | null>(null)
const tagDialogInitialEnglishValue = ref('')
const tagDialogError = ref('')
const loadingOptions = ref(true)
const formError = ref('')
const publishing = ref(false)
const publishedAudioId = ref<number | null>(null)
const discardChangesDialogOpen = ref(false)

interface GeneratedTurnPreview {
  signature: string
  jobId: number
  content: AudioPreviewInput
}

interface TurnPreviewState {
  requestId: number
  pendingSignature: string
  pendingContent: AudioPreviewInput
  pendingJobId: number | null
  status: 'submitting' | JobStatus
  progress: number
  generated?: GeneratedTurnPreview
  errorMessage?: string
}

interface TurnContent extends AudioPreviewInput {
  turnKey: number
}

const previewStates = ref<Record<number, TurnPreviewState>>({})
let previewPollTimer: ReturnType<typeof setTimeout> | undefined
let nextPreviewRequestId = 0

const tagGroups = computed(() => [
  {
    label: 'Topics',
    type: 'topic' as const,
  },
  {
    label: 'Categories',
    type: 'category' as const,
  },
])
const previewPresentations = computed<Record<number, DialogueTurnPreview>>(() => {
  const result: Record<number, DialogueTurnPreview> = {}
  for (const turn of turns.value) {
    const state = previewStates.value[turn.key]
    if (!state) {
      result[turn.key] = { status: 'idle', progress: 0 }
    } else {
      result[turn.key] = {
        status: state.status === 'cancelled' ? 'failed' : state.status,
        progress: state.progress,
        mediaPath: state.generated
          ? audioPreviewMediaPath(state.generated.jobId)
          : undefined,
        errorMessage: state.errorMessage,
      }
    }
  }
  return result
})

const allPreviewsReady = computed(
  () =>
    turns.value.length > 0 &&
    turns.value.every((turn) => Boolean(previewStates.value[turn.key]?.generated)),
)

const hasUnpublishedTurnChanges = computed(() =>
  turns.value.some((turn) => {
    const generated = previewStates.value[turn.key]?.generated
    return Boolean(generated && generated.signature !== turnSignature(turn.key))
  }),
)

const previewGenerationActive = computed(() =>
  Object.values(previewPresentations.value).some((preview) =>
    ['submitting', 'queued', 'running'].includes(preview.status),
  ),
)

function newSpeaker(voiceId?: string): SpeakerDraft {
  const nextKey = Math.max(0, ...speakers.value.map((speaker) => speaker.key)) + 1
  return {
    key: nextKey,
    name: t('Speaker {position}', { position: nextKey }),
    voiceId: voiceId ?? (voices.value[0] ? String(voices.value[0].id) : ''),
  }
}

function newTurn(speakerKey?: number): DialogueTurnDraft {
  const nextKey = Math.max(0, ...turns.value.map((turn) => turn.key)) + 1
  return {
    key: nextKey,
    speakerKey: speakerKey ?? speakers.value[0]?.key ?? '',
    text: '',
  }
}

function removeSpeaker(speakerKey: number): void {
  if (speakers.value.length <= 1) return
  speakers.value = speakers.value.filter((speaker) => speaker.key !== speakerKey)
  const fallbackKey = speakers.value[0]?.key ?? ''
  turns.value = turns.value.map((turn) =>
    turn.speakerKey === speakerKey ? { ...turn, speakerKey: fallbackKey } : turn,
  )
}

function turnContent(turnKey: number): TurnContent | null {
  const turn = turns.value.find((item) => item.key === turnKey)
  if (!turn) return null
  const speaker = speakers.value.find((item) => item.key === turn.speakerKey)
  const voiceId = Number(speaker?.voiceId)
  const speakerDisplayName = speaker?.name.trim() ?? ''
  const text = turn.text.trim()
  if (
    !Number.isInteger(voiceId) ||
    voiceId < 1 ||
    !speakerDisplayName ||
    !text
  ) {
    return null
  }
  return { turnKey, voiceId, speakerDisplayName, text }
}

function turnSignature(turnKey: number): string | null {
  const content = turnContent(turnKey)
  return content
    ? JSON.stringify([content.voiceId, content.speakerDisplayName, content.text])
    : null
}

function validateContent(): TurnContent[] | null {
  const normalizedNames = speakers.value.map((speaker) =>
    speaker.name.trim().normalize('NFKC').toLocaleLowerCase(),
  )
  if (
    speakers.value.some(
      (speaker) =>
        !speaker.name.trim() ||
        !Number.isInteger(Number(speaker.voiceId)) ||
        Number(speaker.voiceId) < 1,
    ) ||
    new Set(normalizedNames).size !== normalizedNames.length
  ) {
    formError.value = t('Complete each speaker with a unique name and voice')
    return null
  }
  const content = turns.value.map((turn) => turnContent(turn.key))
  if (content.some((item) => item === null)) {
    formError.value = t('Select a speaker and enter text for every item')
    return null
  }
  return content as TurnContent[]
}

function schedulePreviewPoll(): void {
  clearTimeout(previewPollTimer)
  const hasActiveJob = Object.values(previewStates.value).some((state) =>
    ['queued', 'running'].includes(state.status),
  )
  if (hasActiveJob) previewPollTimer = setTimeout(refreshPreviewJobs, 1000)
}

async function refreshPreviewJobs(): Promise<void> {
  const active = Object.entries(previewStates.value).filter(
    ([, state]) => state.pendingJobId && ['queued', 'running'].includes(state.status),
  )
  await Promise.all(
    active.map(async ([turnKeyValue, state]) => {
      const turnKey = Number(turnKeyValue)
      const jobId = state.pendingJobId
      if (!jobId) return
      try {
        const job = await getJob(jobId)
        const current = previewStates.value[turnKey]
        if (!current || current.pendingJobId !== jobId) return
        if (job.status === 'succeeded') {
          const previousJobId = current.generated?.jobId
          previewStates.value = {
            ...previewStates.value,
            [turnKey]: {
              ...current,
              pendingJobId: null,
              status: 'succeeded',
              progress: job.progress,
              generated: {
                signature: current.pendingSignature,
                jobId,
                content: current.pendingContent,
              },
              errorMessage: undefined,
            },
          }
          if (previousJobId && previousJobId !== jobId) {
            void deleteAudioPreview(previousJobId).catch(() => undefined)
          }
          return
        }
        previewStates.value = {
          ...previewStates.value,
          [turnKey]: {
            ...current,
            status: job.status,
            progress: job.progress,
            errorMessage: job.errorSummary,
          },
        }
      } catch (error) {
        const current = previewStates.value[turnKey]
        if (!current || current.pendingJobId !== jobId) return
        previewStates.value = {
          ...previewStates.value,
          [turnKey]: {
            ...current,
            status: 'failed',
            errorMessage:
              error instanceof ApiError
                ? error.message
                : t('Preview status could not be loaded'),
          },
        }
      }
    }),
  )
  schedulePreviewPoll()
}

async function generateTurnPreview(turnKey: number): Promise<void> {
  formError.value = ''
  const content = turnContent(turnKey)
  if (!content) {
    formError.value = t('Select a speaker and enter text for every item')
    return
  }
  const signature = JSON.stringify([
    content.voiceId,
    content.speakerDisplayName,
    content.text,
  ])
  const previous = previewStates.value[turnKey]
  const requestId = ++nextPreviewRequestId
  previewStates.value = {
    ...previewStates.value,
    [turnKey]: {
      requestId,
      pendingSignature: signature,
      pendingContent: {
        voiceId: content.voiceId,
        speakerDisplayName: content.speakerDisplayName,
        text: content.text,
      },
      pendingJobId: null,
      status: 'submitting',
      progress: 0,
      generated: previous?.generated,
    },
  }
  try {
    const accepted = await createAudioPreview({
      voiceId: content.voiceId,
      speakerDisplayName: content.speakerDisplayName,
      text: content.text,
    })
    if (previewStates.value[turnKey]?.requestId !== requestId) {
      void deleteAudioPreview(accepted.jobId).catch(() => undefined)
      return
    }
    previewStates.value = {
      ...previewStates.value,
      [turnKey]: {
        requestId,
        pendingSignature: signature,
        pendingContent: {
          voiceId: content.voiceId,
          speakerDisplayName: content.speakerDisplayName,
          text: content.text,
        },
        pendingJobId: accepted.jobId,
        status: 'queued',
        progress: 0,
        generated: previous?.generated,
      },
    }
    if (
      previous?.pendingJobId &&
      previous.pendingJobId !== accepted.jobId &&
      previous.pendingJobId !== previous.generated?.jobId
    ) {
      void deleteAudioPreview(previous.pendingJobId).catch(() => undefined)
    }
    await refreshPreviewJobs()
  } catch (error) {
    if (previewStates.value[turnKey]?.requestId !== requestId) return
    previewStates.value = {
      ...previewStates.value,
      [turnKey]: {
        requestId,
        pendingSignature: signature,
        pendingContent: {
          voiceId: content.voiceId,
          speakerDisplayName: content.speakerDisplayName,
          text: content.text,
        },
        pendingJobId: null,
        status: 'failed',
        progress: 0,
        generated: previous?.generated,
        errorMessage:
          error instanceof ApiError ? error.message : t('Preview could not be submitted'),
      },
    }
  }
}

async function generateMissingPreviews(): Promise<void> {
  formError.value = ''
  const content = validateContent()
  if (!content) return
  const missing = content.filter(
    (item) => !previewStates.value[item.turnKey]?.generated,
  )
  await Promise.all(missing.map((item) => generateTurnPreview(item.turnKey)))
}

async function removeTurnPreview(turnKey: number): Promise<void> {
  const state = previewStates.value[turnKey]
  const next = { ...previewStates.value }
  delete next[turnKey]
  previewStates.value = next
  const jobIds = new Set(
    [state?.pendingJobId, state?.generated?.jobId].filter(
      (jobId): jobId is number => typeof jobId === 'number',
    ),
  )
  await Promise.allSettled([...jobIds].map((jobId) => deleteAudioPreview(jobId)))
}

function selectTag(tagId: number): void {
  if (!selectedTagIds.value.includes(tagId)) {
    selectedTagIds.value = [...selectedTagIds.value, tagId]
  }
}

function removeTag(tagId: number): void {
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

async function loadOptions(): Promise<void> {
  loadingOptions.value = true
  formError.value = ''
  try {
    const [voiceResponse, tagResponse] = await Promise.all([
      listVoices({ language: locale.value }),
      listAudioCreationTags(locale.value),
    ])
    voices.value = voiceResponse.items.filter((voice) => voice.status === 'ready')
    tags.value = tagResponse
    const requestedVoice = Number(route.query.voice)
    const selected = voices.value.find((voice) => voice.id === requestedVoice)
    const voiceId = selected
      ? String(selected.id)
      : voices.value[0]
        ? String(voices.value[0].id)
        : ''
    if (speakers.value.length === 0) speakers.value = [newSpeaker(voiceId)]
    if (turns.value.length === 0) turns.value = [newTurn(speakers.value[0]?.key)]
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Creation options could not be loaded')
  } finally {
    loadingOptions.value = false
  }
}

async function submit(): Promise<void> {
  formError.value = ''
  if (!allPreviewsReady.value) {
    await generateMissingPreviews()
    return
  }
  if (!title.value.trim()) {
    formError.value = t('Enter a title')
    return
  }
  if (hasUnpublishedTurnChanges.value) {
    discardChangesDialogOpen.value = true
    return
  }
  await publishGeneratedAudio()
}

async function publishGeneratedAudio(): Promise<void> {
  formError.value = ''
  const normalizedTitle = title.value.trim()
  if (!normalizedTitle) {
    formError.value = t('Enter a title')
    return
  }
  const utterances = turns.value.map((turn) => {
    const generated = previewStates.value[turn.key]?.generated
    return generated
      ? {
          previewJobId: generated.jobId,
          voiceId: generated.content.voiceId,
          speakerDisplayName: generated.content.speakerDisplayName,
          text: generated.content.text,
        }
      : null
  })
  if (utterances.some((item) => item === null)) return
  publishing.value = true
  try {
    const audio = await publishAudioFromPreviews({
      title: normalizedTitle,
      utterances: utterances as NonNullable<(typeof utterances)[number]>[],
      tagIds: selectedTagIds.value,
      visibility: visibility.value,
    })
    publishedAudioId.value = audio.id
    previewStates.value = {}
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Audio could not be published')
  } finally {
    publishing.value = false
  }
}

async function confirmDiscardChangesAndPublish(): Promise<void> {
  discardChangesDialogOpen.value = false
  await publishGeneratedAudio()
}

function startAnother(): void {
  publishedAudioId.value = null
  title.value = ''
  speakers.value = []
  speakers.value = [newSpeaker()]
  turns.value = [newTurn(speakers.value[0]?.key)]
  selectedTagIds.value = []
  visibility.value = 'private'
  formError.value = ''
  discardChangesDialogOpen.value = false
}

async function cleanupPreviews(): Promise<void> {
  clearTimeout(previewPollTimer)
  const jobIds = [
    ...new Set(
      Object.values(previewStates.value)
        .flatMap((state) => [state.pendingJobId, state.generated?.jobId])
        .filter((jobId): jobId is number => typeof jobId === 'number'),
    ),
  ]
  previewStates.value = {}
  await Promise.allSettled(jobIds.map((jobId) => deleteAudioPreview(jobId)))
}

onMounted(() => {
  void loadOptions()
})
onBeforeRouteLeave(async () => {
  if (!publishedAudioId.value) await cleanupPreviews()
})
onUnmounted(() => clearTimeout(previewPollTimer))
</script>

<template>
  <section aria-labelledby="create-title" class="page-shell min-w-0">
    <div class="page-heading">
      <div class="min-w-0">
        <p class="eyebrow">{{ t('Teacher workspace') }}</p>
        <h1 id="create-title" class="break-words text-3xl font-semibold">{{ t('Create listening') }}</h1>
      </div>
      <RouterLink
        to="/voices/create"
        class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 3a5 5 0 0 0-5 5v4a5 5 0 0 0 10 0V8a5 5 0 0 0-5-5Z" stroke="currentColor" stroke-width="2" />
          <path d="M4 11v1a8 8 0 0 0 16 0v-1M12 20v2" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Create voice') }}
      </RouterLink>
    </div>

    <div v-if="publishedAudioId" class="mt-6 rounded-lg border border-line bg-surface px-5 py-9 shadow-panel">
      <p class="text-base font-semibold text-success">{{ t('Audio is ready') }}</p>
      <div class="mt-5 flex flex-wrap gap-3">
        <RouterLink
          :to="`/audio/${publishedAudioId}`"
          class="inline-flex h-10 items-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent"
        >
          {{ t('View audio') }}
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
          </svg>
        </RouterLink>
        <button type="button" class="h-10 border border-line bg-surface px-4 text-sm font-medium hover:border-ink" @click="startAnother">
          {{ t('Create another') }}
        </button>
      </div>
    </div>

    <form v-else class="mt-6 min-w-0 overflow-hidden rounded-lg border border-line bg-surface shadow-panel" @submit.prevent="submit">
      <div class="border-b border-line px-5 py-6">
        <div class="min-w-0">
          <label for="audio-title" class="mb-1 block text-sm font-medium">{{ t('Title') }}</label>
          <input
            id="audio-title"
            v-model="title"
            type="text"
            maxlength="200"
            class="h-10 w-full min-w-0 border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>
      </div>

      <div v-if="loadingOptions" class="border-b border-line px-5 py-12 text-sm text-muted">{{ t('Loading options') }}</div>
      <div v-else-if="voices.length === 0" class="border-b border-line px-5 py-10">
        <p class="text-sm text-muted">{{ t('No ready voices are available') }}</p>
        <RouterLink to="/voices/create" class="mt-3 inline-block text-sm font-medium text-accent underline">{{ t('Create voice') }}</RouterLink>
      </div>

      <SpeakerDefinitionsEditor
        v-if="!loadingOptions && voices.length > 0"
        v-model="speakers"
        :voices="voices"
        @remove="removeSpeaker"
      />

      <DialogueTurnsEditor
        v-if="!loadingOptions && voices.length > 0"
        v-model="turns"
        :speakers="speakers"
        :previews="previewPresentations"
        @generate="generateTurnPreview"
        @remove="removeTurnPreview"
      />

      <div class="grid min-w-0 gap-6 px-5 py-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="grid min-w-0 gap-5 sm:grid-cols-2">
          <ResourceTagPicker
            v-for="group in tagGroups"
            :key="group.type"
            :label="group.label"
            :type="group.type"
            :tags="tags"
            :selected-ids="selectedTagIds"
            @select="selectTag"
            @remove="removeTag"
            @create="openTagDialog(group.type, $event)"
          />
        </div>
        <div class="flex flex-col justify-between gap-6">
          <label class="flex items-start gap-3">
            <input type="checkbox" class="mt-0.5 h-4 w-4 accent-accent" :checked="visibility === 'public'" @change="visibility = ($event.target as HTMLInputElement).checked ? 'public' : 'private'" />
            <span class="text-sm font-medium">{{ t('Publish when ready') }}</span>
          </label>
          <div>
            <p v-if="formError" role="alert" class="mb-3 break-words text-sm text-danger">{{ formError }}</p>
            <button type="submit" :disabled="publishing || previewGenerationActive || loadingOptions || voices.length === 0" class="inline-flex h-10 w-full items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50">
              <svg v-if="allPreviewsReady" viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 12.5 9.5 17 19 7" stroke="currentColor" stroke-width="2" /></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M8 5v14l11-7Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" /></svg>
              {{ publishing ? t('Submitting') : allPreviewsReady ? t('Publish') : t('Generate audio') }}
            </button>
          </div>
        </div>
      </div>
    </form>

    <TagCreationDialog
      :open="tagDialogType !== null"
      :type="tagDialogType"
      :initial-english-value="tagDialogInitialEnglishValue"
      :busy="creatingTagType !== null"
      :error-message="tagDialogError"
      @close="closeTagDialog"
      @submit="createAndAddTag"
    />

    <ConfirmDialog
      :open="discardChangesDialogOpen"
      :title="t('Publish generated audio?')"
      :busy="publishing"
      confirm-label="Publish"
      @close="discardChangesDialogOpen = false"
      @confirm="confirmDiscardChangesAndPublish"
    >
      {{ t('Changes made after preview generation will be discarded. The last generated audio will be published instead.') }}
    </ConfirmDialog>
  </section>
</template>
