<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, RouterLink, useRoute } from 'vue-router'

import {
  reviseGenerationDraft,
  type GenerationDraft,
} from '@/api/generationBatches'
import {
  audioPreviewMediaPath,
  createAudioPreview,
  createAudioTurnPreview,
  createAudioTag,
  deleteAudioPreview,
  getAudioCreationDraft,
  listAudioCreationTags,
  publishAudioFromPreviews,
  uploadAudioPreview,
  type AudioTag,
  type AudioCreationDraft,
  type AudioQuestionInput,
  type AudioPreviewInput,
  type ResourceVisibility,
} from '@/api/audios'
import { getJob, type JobStatus } from '@/api/jobs'
import { listVoices, type Voice } from '@/api/voices'
import { ApiError } from '@/api/errors'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import AudioQuestionsEditor from '@/components/AudioQuestionsEditor.vue'
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
import { useListeningDraftsStore, type ListeningDraft } from '@/stores/listeningDrafts'
import { useAuthStore } from '@/stores/auth'

type CreationTagType = 'topic' | 'category'

const route = useRoute()
const { locale, t } = useI18n()
const draftStore = useListeningDraftsStore()
const auth = useAuthStore()
const title = ref('')
const speakers = ref<SpeakerDraft[]>([])
const turns = ref<DialogueTurnDraft[]>([])
const visibility = ref<ResourceVisibility>('public')
const selectedTagIds = ref<number[]>([])
const voices = ref<Voice[]>([])
const tags = ref<AudioTag[]>([])
const questions = ref<AudioQuestionInput[]>([])
const creatingTagType = ref<CreationTagType | null>(null)
const tagDialogType = ref<CreationTagType | null>(null)
const tagDialogInitialEnglishValue = ref('')
const tagDialogError = ref('')
const loadingOptions = ref(true)
const formError = ref('')
const publishing = ref(false)
const publishedAudioId = ref<number | null>(null)
const discardChangesDialogOpen = ref(false)
const batchResults = ref<{ title: string; audioId: number }[]>([])
const batchFailures = ref<string[]>([])
const aiEditorOpen = ref(false)
const aiPrompts = ref<Record<number, string>>({})
const aiRevisionErrors = ref<Record<number, string>>({})
const revisingDraftIndex = ref<number | null>(null)

interface DraftRevisionHistory {
  past: ListeningDraft[]
  future: ListeningDraft[]
}

const draftRevisionHistories = ref<Record<number, DraftRevisionHistory>>({})

interface GeneratedTurnPreview {
  source: 'generated' | 'upload'
  signature: string
  speakerKey: number
  content: AudioPreviewInput
  segments: GeneratedPreviewSegment[]
}

interface GeneratedPreviewSegment {
  text: string
  jobId: number
}

interface TurnPreviewSegmentState {
  text: string
  requestId: number
  pendingJobId: number | null
  readyJobId?: number
  status: 'submitting' | JobStatus
  progress: number
  errorMessage?: string
}

interface TurnPreviewState {
  requestId: number
  pendingSignature: string
  pendingSpeakerKey: number
  pendingContent: AudioPreviewInput
  status: 'submitting' | JobStatus
  progress: number
  segments: TurnPreviewSegmentState[]
  generated?: GeneratedTurnPreview
  errorMessage?: string
}

interface TurnContent extends AudioPreviewInput {
  turnKey: number
}

const standalonePreviewStates = ref<Record<number, TurnPreviewState>>({})
const batchPreviewStates = ref<Record<number, Record<number, TurnPreviewState>>>({})
let previewPollTimer: ReturnType<typeof setTimeout> | undefined
let nextPreviewRequestId = 0

const batchMode = computed(
  () =>
    draftStore.drafts.length > 0 &&
    String(draftStore.sourceBatchId) === String(route.query.batch ?? ''),
)

const previewStates = computed(() =>
  batchMode.value
    ? batchPreviewStates.value[draftStore.currentIndex] ?? {}
    : standalonePreviewStates.value,
)

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
      result[turn.key] = { status: 'idle', progress: 0, segments: [] }
    } else {
      result[turn.key] = {
        status: state.status === 'cancelled' ? 'failed' : state.status,
        progress: state.progress,
        errorMessage: state.errorMessage,
        segments: state.segments.map((segment) => ({
          text: segment.text,
          status: segment.status === 'cancelled' ? 'failed' : segment.status,
          progress: segment.progress,
          mediaPath: segment.readyJobId
            ? audioPreviewMediaPath(segment.readyJobId)
            : undefined,
          errorMessage: segment.errorMessage,
        })),
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

const allBatchPreviewsReady = computed(
  () =>
    draftStore.drafts.length > 0 &&
    draftStore.drafts.every((draft, draftIndex) =>
      draft.utterances.every((_, turnIndex) =>
        Boolean(batchPreviewStates.value[draftIndex]?.[turnIndex + 1]?.generated),
      ),
    ),
)

const hasUnpublishedTurnChanges = computed(() =>
  turns.value.some((turn) => {
    const generated = previewStates.value[turn.key]?.generated
    return Boolean(
      generated &&
      generated.source === 'generated' &&
      generated.signature !== turnSignature(turn.key),
    )
  }),
)

const batchHasUnpublishedTurnChanges = computed(() =>
  draftStore.drafts.some((draft, draftIndex) =>
    draft.utterances.some((utterance, turnIndex) => {
      const generated = batchPreviewStates.value[draftIndex]?.[turnIndex + 1]?.generated
      return Boolean(
        generated &&
        generated.source === 'generated' &&
        generated.signature !== contentSignature(utterance, utterance.speakerKey),
      )
    }),
  ),
)

const previewGenerationActive = computed(() =>
  previewStateEntries().some(({ state }) =>
    ['submitting', 'queued', 'running'].includes(state.status),
  ),
)

function previewBucket(draftIndex = draftStore.currentIndex): Record<number, TurnPreviewState> {
  return batchMode.value
    ? batchPreviewStates.value[draftIndex] ?? {}
    : standalonePreviewStates.value
}

function replacePreviewBucket(
  states: Record<number, TurnPreviewState>,
  draftIndex = draftStore.currentIndex,
): void {
  if (batchMode.value) {
    batchPreviewStates.value = { ...batchPreviewStates.value, [draftIndex]: states }
  } else {
    standalonePreviewStates.value = states
  }
}

function previewStateEntries(): Array<{
  draftIndex: number
  turnKey: number
  state: TurnPreviewState
}> {
  if (!batchMode.value) {
    return Object.entries(standalonePreviewStates.value).map(([turnKey, state]) => ({
      draftIndex: 0,
      turnKey: Number(turnKey),
      state,
    }))
  }
  return Object.entries(batchPreviewStates.value).flatMap(([draftIndex, states]) =>
    Object.entries(states).map(([turnKey, state]) => ({
      draftIndex: Number(draftIndex),
      turnKey: Number(turnKey),
      state,
    })),
  )
}

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

function applyDraft(draft: ListeningDraft): void {
  const speakerKeys = new Map<string, number>()
  const nextSpeakers: SpeakerDraft[] = []
  const nextTurns: DialogueTurnDraft[] = []
  for (const [index, utterance] of draft.utterances.entries()) {
    const identity = utterance.speakerDisplayName.normalize('NFKC').toLocaleLowerCase()
    let speakerKey = speakerKeys.get(identity)
    if (speakerKey === undefined) {
      speakerKey = utterance.speakerKey
      speakerKeys.set(identity, speakerKey)
      nextSpeakers.push({
        key: speakerKey,
        name: utterance.speakerDisplayName,
        voiceId: String(utterance.voiceId),
      })
    }
    nextTurns.push({ key: index + 1, speakerKey, text: utterance.text })
  }
  title.value = draft.title
  speakers.value = nextSpeakers
  turns.value = nextTurns
  questions.value = cloneQuestions(draft.questions)
  selectedTagIds.value = [...draft.tagIds]
  visibility.value = 'public'
  formError.value = ''
}

function applyCreationDraft(draft: AudioCreationDraft): void {
  const sourceUtterances = draft.utterances.length > 0
    ? draft.utterances
    : [{
        voiceId: null,
        speakerDisplayName: t('Speaker {position}', { position: 1 }),
        text: draft.text,
      }]
  applyDraft({
    title: draft.title,
    questionType: 'monologue',
    utterances: sourceUtterances.map((utterance, index) => ({
      ...utterance,
      speakerKey: index + 1,
      voiceId: utterance.voiceId ?? 0,
    })),
    questions: draft.questions,
    tagIds: draft.tagIds,
  })
  const availableVoiceIds = new Set(voices.value.map((voice) => voice.id))
  if (sourceUtterances.some((utterance) => !availableVoiceIds.has(utterance.voiceId ?? 0))) {
    formError.value = t(
      'Some voices from this audio are unavailable. Select replacement voices to continue.',
    )
  }
}

function currentDraft(): ListeningDraft | null {
  const utterances = turns.value.map((turn) => {
    const speaker = speakers.value.find((item) => item.key === turn.speakerKey)
    return {
      speakerKey: Number(turn.speakerKey),
      speakerDisplayName: speaker?.name ?? '',
      voiceId: Number(speaker?.voiceId),
      text: turn.text,
    }
  })
  const original = draftStore.activeDraft
  if (!original) return null
  return {
    title: title.value,
    questionType: original.questionType,
    utterances,
    questions: cloneQuestions(questions.value),
    tagIds: [...selectedTagIds.value],
  }
}

function cloneQuestions(values: AudioQuestionInput[]): AudioQuestionInput[] {
  return values.map((question) => ({
    prompt: question.prompt,
    correctAnswers: [...question.correctAnswers],
    incorrectAnswers: [...question.incorrectAnswers],
  }))
}

function cloneDraft(draft: ListeningDraft): ListeningDraft {
  return {
    ...draft,
    utterances: draft.utterances.map((utterance) => ({ ...utterance })),
    questions: cloneQuestions(draft.questions),
    tagIds: [...draft.tagIds],
  }
}

function revisionHistory(index = draftStore.currentIndex): DraftRevisionHistory {
  return draftRevisionHistories.value[index] ?? { past: [], future: [] }
}

function replaceRevisionHistory(index: number, history: DraftRevisionHistory): void {
  draftRevisionHistories.value = {
    ...draftRevisionHistories.value,
    [index]: history,
  }
}

function applyRevisionDraft(draft: ListeningDraft): void {
  draftStore.updateDraft(draftStore.currentIndex, cloneDraft(draft))
  applyDraft(draft)
}

function generationDraft(draft: ListeningDraft): GenerationDraft {
  return {
    questionType: draft.questionType,
    title: draft.title,
    utterances: draft.utterances.map(({ speakerDisplayName, voiceId, text }) => ({
      speakerDisplayName,
      voiceId,
      text,
    })),
    questions: cloneQuestions(draft.questions),
  }
}

async function reviseActiveDraft(): Promise<void> {
  const batchId = draftStore.sourceBatchId
  const prompt = aiPrompts.value[draftStore.currentIndex]?.trim() ?? ''
  if (!batchMode.value || batchId === null || !prompt) return
  saveActiveDraft()
  const source = draftStore.activeDraft
  if (!source) return
  const index = draftStore.currentIndex
  revisingDraftIndex.value = index
  aiRevisionErrors.value = { ...aiRevisionErrors.value, [index]: '' }
  try {
    const revised = await reviseGenerationDraft(batchId, prompt, generationDraft(source))
    if (draftStore.currentIndex !== index) return
    const speakerKeys = new Map(
      source.utterances.map((utterance) => [utterance.speakerDisplayName, utterance.speakerKey]),
    )
    const beforeApply = currentDraft() ?? source
    const next: ListeningDraft = {
      ...revised,
      utterances: revised.utterances.map((utterance) => ({
        ...utterance,
        speakerKey: speakerKeys.get(utterance.speakerDisplayName) ?? 0,
      })),
      tagIds: [...beforeApply.tagIds],
    }
    const history = revisionHistory(index)
    replaceRevisionHistory(index, {
      past: [...history.past, cloneDraft(beforeApply)],
      future: [],
    })
    applyRevisionDraft(next)
  } catch (error) {
    aiRevisionErrors.value = {
      ...aiRevisionErrors.value,
      [index]: error instanceof ApiError ? error.message : t('AI revision failed'),
    }
  } finally {
    if (revisingDraftIndex.value === index) revisingDraftIndex.value = null
  }
}

function undoDraftRevision(): void {
  saveActiveDraft()
  const current = draftStore.activeDraft
  const history = revisionHistory()
  const previous = history.past[history.past.length - 1]
  if (!current || !previous) return
  replaceRevisionHistory(draftStore.currentIndex, {
    past: history.past.slice(0, -1),
    future: [cloneDraft(current), ...history.future],
  })
  applyRevisionDraft(previous)
}

function redoDraftRevision(): void {
  saveActiveDraft()
  const current = draftStore.activeDraft
  const history = revisionHistory()
  const next = history.future[0]
  if (!current || !next) return
  replaceRevisionHistory(draftStore.currentIndex, {
    past: [...history.past, cloneDraft(current)],
    future: history.future.slice(1),
  })
  applyRevisionDraft(next)
}

function saveActiveDraft(): void {
  const draft = currentDraft()
  if (!draft) return
  if (batchMode.value) {
    const currentStates = previewBucket()
    const normalizedStates: Record<number, TurnPreviewState> = {}
    turns.value.forEach((turn, index) => {
      const state = currentStates[turn.key]
      if (state) normalizedStates[index + 1] = state
    })
    replacePreviewBucket(normalizedStates)
    turns.value = turns.value.map((turn, index) => ({ ...turn, key: index + 1 }))
  }
  draftStore.updateDraft(draftStore.currentIndex, draft)
}

async function selectDraft(index: number): Promise<void> {
  if (index < 0 || index >= draftStore.drafts.length || index === draftStore.currentIndex) return
  saveActiveDraft()
  clearTimeout(previewPollTimer)
  draftStore.currentIndex = index
  const draft = draftStore.activeDraft
  if (draft) applyDraft(draft)
  schedulePreviewPoll()
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
  const turn = turns.value.find((item) => item.key === turnKey)
  const content = turnContent(turnKey)
  return content && turn
    ? contentSignature(content, Number(turn.speakerKey))
    : null
}

function contentSignature(content: AudioPreviewInput, speakerKey: number): string {
  return JSON.stringify([
    speakerKey,
    content.voiceId,
    content.text.trim(),
  ])
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

function normalizedQuestions(): AudioQuestionInput[] | null {
  if (
    questions.value.some(
      (question) =>
        !question.prompt.trim() ||
        question.correctAnswers.length === 0 ||
        question.incorrectAnswers.length === 0 ||
        question.correctAnswers.some((answer) => !answer.trim()) ||
        question.incorrectAnswers.some((answer) => !answer.trim()),
    )
  ) {
    formError.value = t('Complete every question and answer')
    return null
  }
  return questions.value.map((question) => ({
    prompt: question.prompt.trim(),
    correctAnswers: question.correctAnswers.map((answer) => answer.trim()),
    incorrectAnswers: question.incorrectAnswers.map((answer) => answer.trim()),
  }))
}

function schedulePreviewPoll(): void {
  clearTimeout(previewPollTimer)
  const hasActiveJob = previewStateEntries().some(({ state }) =>
    state.segments.some(
      (segment) =>
        segment.pendingJobId !== null &&
        ['queued', 'running'].includes(segment.status),
    ),
  )
  if (hasActiveJob) previewPollTimer = setTimeout(refreshPreviewJobs, 1000)
}

async function refreshPreviewJobs(): Promise<void> {
  const active = previewStateEntries().flatMap(({ draftIndex, turnKey, state }) =>
    state.segments.flatMap((segment, segmentIndex) =>
      segment.pendingJobId !== null && ['queued', 'running'].includes(segment.status)
        ? [{ draftIndex, turnKey, segmentIndex, segment }]
        : [],
    ),
  )
  for (const { draftIndex, turnKey, segmentIndex, segment } of active) {
    const jobId = segment.pendingJobId
    if (!jobId) continue
    try {
      const job = await getJob(jobId)
      const states = previewBucket(draftIndex)
      const current = states[turnKey]
      const currentSegment = current?.segments[segmentIndex]
      if (!current || currentSegment?.pendingJobId !== jobId) continue
      if (job.status === 'succeeded') {
        const segments = current.segments.map((item, position) =>
          position === segmentIndex
            ? {
                ...item,
                pendingJobId: null,
                readyJobId: jobId,
                status: 'succeeded' as const,
                progress: job.progress,
                errorMessage: undefined,
              }
            : item,
        )
        const completed = completeTurnPreview({ ...current, segments })
        const completedJobIds = new Set(
          completed.generated?.segments.map((item) => item.jobId) ?? [],
        )
        const obsoleteJobIds = completed.status === 'succeeded'
          ? current.generated?.segments
              .map((item) => item.jobId)
              .filter((item) => !completedJobIds.has(item)) ?? []
          : []
        replacePreviewBucket(
          { ...states, [turnKey]: completed },
          draftIndex,
        )
        void Promise.allSettled(
          obsoleteJobIds.map((item) => deleteAudioPreview(item)),
        )
        continue
      }
      const segments = current.segments.map((item, position) =>
        position === segmentIndex
          ? {
              ...item,
              status: job.status,
              progress: job.progress,
              errorMessage: job.errorSummary,
            }
          : item,
      )
      replacePreviewBucket(
        { ...states, [turnKey]: summarizeTurnPreview({ ...current, segments }) },
        draftIndex,
      )
    } catch (error) {
      const states = previewBucket(draftIndex)
      const current = states[turnKey]
      if (!current || current.segments[segmentIndex]?.pendingJobId !== jobId) continue
      const segments = current.segments.map((item, position) =>
        position === segmentIndex
          ? {
              ...item,
              status: 'failed' as const,
              errorMessage:
                error instanceof ApiError
                  ? error.message
                  : t('Preview status could not be loaded'),
            }
          : item,
      )
      replacePreviewBucket(
        { ...states, [turnKey]: summarizeTurnPreview({ ...current, segments }) },
        draftIndex,
      )
    }
  }
  schedulePreviewPoll()
}

function summarizeTurnPreview(state: TurnPreviewState): TurnPreviewState {
  const statuses = state.segments.map((segment) => segment.status)
  const status = statuses.includes('running')
    ? 'running'
    : statuses.includes('queued')
      ? 'queued'
      : statuses.includes('submitting')
        ? 'submitting'
        : statuses.includes('failed') || statuses.includes('cancelled')
          ? 'failed'
          : statuses.length > 0 && statuses.every((item) => item === 'succeeded')
            ? 'succeeded'
            : 'queued'
  const progress = state.segments.length
    ? Math.round(
        state.segments.reduce((sum, segment) => sum + segment.progress, 0) /
          state.segments.length,
      )
    : 0
  return { ...state, status, progress }
}

function completeTurnPreview(state: TurnPreviewState): TurnPreviewState {
  const summarized = summarizeTurnPreview(state)
  if (
    summarized.status !== 'succeeded' ||
    summarized.segments.some((segment) => !segment.readyJobId)
  ) {
    return summarized
  }
  return {
    ...summarized,
    generated: {
      source: 'generated',
      signature: summarized.pendingSignature,
      speakerKey: summarized.pendingSpeakerKey,
      content: summarized.pendingContent,
      segments: summarized.segments.map((segment) => ({
        text: segment.text,
        jobId: segment.readyJobId!,
      })),
    },
    errorMessage: undefined,
  }
}

async function generateTurnPreview(turnKey: number): Promise<void> {
  formError.value = ''
  const content = turnContent(turnKey)
  if (!content) {
    formError.value = t('Select a speaker and enter text for every item')
    return
  }
  const turn = turns.value.find((item) => item.key === turnKey)
  if (!turn) return
  await generatePreview(
    turnKey,
    content,
    Number(turn.speakerKey),
    draftStore.currentIndex,
  )
}

async function generatePreview(
  turnKey: number,
  content: AudioPreviewInput,
  speakerKey: number,
  draftIndex: number,
  refreshAfterSubmit = true,
): Promise<void> {
  const signature = contentSignature(content, speakerKey)
  const states = previewBucket(draftIndex)
  const previous = states[turnKey]
  const requestId = ++nextPreviewRequestId
  replacePreviewBucket({
    ...states,
    [turnKey]: {
      requestId,
      pendingSignature: signature,
      pendingSpeakerKey: speakerKey,
      pendingContent: {
        voiceId: content.voiceId,
        speakerDisplayName: content.speakerDisplayName,
        text: content.text,
      },
      status: 'submitting',
      progress: 0,
      segments: previous?.segments ?? [],
      generated: previous?.generated,
    },
  }, draftIndex)
  try {
    const accepted = await createAudioTurnPreview({
      voiceId: content.voiceId,
      speakerDisplayName: content.speakerDisplayName,
      text: content.text,
    })
    if (previewBucket(draftIndex)[turnKey]?.requestId !== requestId) {
      void Promise.allSettled(
        accepted.segments.map((segment) => deleteAudioPreview(segment.jobId)),
      )
      return
    }
    replacePreviewBucket({
      ...previewBucket(draftIndex),
      [turnKey]: {
        requestId,
        pendingSignature: signature,
        pendingSpeakerKey: speakerKey,
        pendingContent: {
          voiceId: content.voiceId,
          speakerDisplayName: content.speakerDisplayName,
          text: content.text,
        },
        status: 'queued',
        progress: 0,
        segments: accepted.segments.map((segment) => {
          const previousSegment = previous?.generated?.segments[segment.position]
          return {
            text: segment.text,
            requestId: ++nextPreviewRequestId,
            pendingJobId: segment.jobId,
            readyJobId:
              previousSegment?.text === segment.text
                ? previousSegment.jobId
                : undefined,
            status: 'queued',
            progress: 0,
          }
        }),
        generated: previous?.generated,
      },
    }, draftIndex)
    const generatedJobIds = new Set(
      previous?.generated?.segments.map((segment) => segment.jobId) ?? [],
    )
    const abandonedJobIds = previous?.segments
      .flatMap((segment) => segment.pendingJobId ?? [])
      .filter((jobId) => !generatedJobIds.has(jobId)) ?? []
    void Promise.allSettled(
      abandonedJobIds.map((jobId) => deleteAudioPreview(jobId)),
    )
    if (refreshAfterSubmit) await refreshPreviewJobs()
  } catch (error) {
    if (previewBucket(draftIndex)[turnKey]?.requestId !== requestId) return
    replacePreviewBucket({
      ...previewBucket(draftIndex),
      [turnKey]: {
        requestId,
        pendingSignature: signature,
        pendingSpeakerKey: speakerKey,
        pendingContent: {
          voiceId: content.voiceId,
          speakerDisplayName: content.speakerDisplayName,
          text: content.text,
        },
        status: 'failed',
        progress: 0,
        segments: previous?.segments ?? [],
        generated: previous?.generated,
        errorMessage:
          error instanceof ApiError ? error.message : t('Preview could not be submitted'),
      },
    }, draftIndex)
  }
}

async function regeneratePreviewSegment(
  turnKey: number,
  segmentPosition: number,
): Promise<void> {
  const states = previewBucket()
  const state = states[turnKey]
  const segment = state?.segments[segmentPosition]
  if (!state || !segment) return
  const previousPendingJobId = segment.pendingJobId
  const requestId = ++nextPreviewRequestId
  const segments = state.segments.map((item, position) =>
    position === segmentPosition
      ? {
          ...item,
          requestId,
          pendingJobId: null,
          status: 'submitting' as const,
          progress: 0,
          errorMessage: undefined,
        }
      : item,
  )
  replacePreviewBucket({
    ...states,
    [turnKey]: summarizeTurnPreview({ ...state, segments }),
  })
  try {
    const accepted = await createAudioPreview({
      voiceId: state.pendingContent.voiceId,
      speakerDisplayName: state.pendingContent.speakerDisplayName,
      text: segment.text,
    })
    const current = previewStates.value[turnKey]
    if (current?.segments[segmentPosition]?.requestId !== requestId) {
      void deleteAudioPreview(accepted.jobId).catch(() => undefined)
      return
    }
    const acceptedSegments = current.segments.map((item, position) =>
      position === segmentPosition
        ? {
            ...item,
            pendingJobId: accepted.jobId,
            status: 'queued' as const,
            progress: 0,
          }
        : item,
    )
    replacePreviewBucket({
      ...previewStates.value,
      [turnKey]: summarizeTurnPreview({ ...current, segments: acceptedSegments }),
    })
    if (
      previousPendingJobId &&
      previousPendingJobId !== accepted.jobId &&
      previousPendingJobId !== segment.readyJobId
    ) {
      void deleteAudioPreview(previousPendingJobId).catch(() => undefined)
    }
    await refreshPreviewJobs()
  } catch (error) {
    const current = previewStates.value[turnKey]
    if (!current || current.segments[segmentPosition]?.requestId !== requestId) return
    const failedSegments = current.segments.map((item, position) =>
      position === segmentPosition
        ? {
            ...item,
            pendingJobId: null,
            status: 'failed' as const,
            progress: 0,
            errorMessage:
              error instanceof ApiError
                ? error.message
                : t('Preview could not be submitted'),
          }
        : item,
    )
    replacePreviewBucket({
      ...previewStates.value,
      [turnKey]: summarizeTurnPreview({ ...current, segments: failedSegments }),
    })
  }
}

async function uploadTurnPreview(turnKey: number, file: File): Promise<void> {
  formError.value = ''
  const turn = turns.value.find((item) => item.key === turnKey)
  if (!turn) return
  const speaker = speakers.value.find((item) => item.key === turn.speakerKey)
  const content: AudioPreviewInput = {
    voiceId: Number(speaker?.voiceId) || 0,
    speakerDisplayName: speaker?.name.trim() ?? '',
    text: turn.text.trim(),
  }
  const signature = 'upload'
  const states = previewBucket()
  const previous = states[turnKey]
  const requestId = ++nextPreviewRequestId
  replacePreviewBucket({
    ...states,
    [turnKey]: {
      requestId,
      pendingSignature: signature,
      pendingSpeakerKey: Number(turn.speakerKey),
      pendingContent: content,
      status: 'submitting',
      progress: 0,
      segments: previous?.segments ?? [],
      generated: previous?.generated,
    },
  })
  try {
    const accepted = await uploadAudioPreview(file)
    if (previewStates.value[turnKey]?.requestId !== requestId) {
      void deleteAudioPreview(accepted.jobId).catch(() => undefined)
      return
    }
    replacePreviewBucket({
      ...previewStates.value,
      [turnKey]: {
        requestId,
        pendingSignature: signature,
        pendingSpeakerKey: Number(turn.speakerKey),
        pendingContent: content,
        status: 'succeeded',
        progress: 100,
        segments: [
          {
            text: content.text,
            requestId,
            pendingJobId: null,
            readyJobId: accepted.jobId,
            status: 'succeeded',
            progress: 100,
          },
        ],
        generated: {
          source: 'upload',
          signature,
          speakerKey: Number(turn.speakerKey),
          content,
          segments: [{ text: content.text, jobId: accepted.jobId }],
        },
      },
    })
    const previousJobIds = previewJobIds(previous)
    void Promise.allSettled(
      previousJobIds
        .filter((jobId) => jobId !== accepted.jobId)
        .map((jobId) => deleteAudioPreview(jobId)),
    )
  } catch (error) {
    if (previewStates.value[turnKey]?.requestId !== requestId) return
    replacePreviewBucket({
      ...previewStates.value,
      [turnKey]: {
        requestId,
        pendingSignature: signature,
        pendingSpeakerKey: Number(turn.speakerKey),
        pendingContent: content,
        status: 'failed',
        progress: 0,
        segments: previous?.segments ?? [],
        generated: previous?.generated,
        errorMessage:
          error instanceof ApiError ? error.message : t('Audio preview could not be uploaded'),
      },
    })
  }
}

async function generateMissingPreviews(): Promise<void> {
  formError.value = ''
  const content = validateContent()
  if (!content) return
  const missing = content.filter(
    (item) => !previewStates.value[item.turnKey]?.generated,
  )
  await Promise.all(
    missing.map((item) => {
      const turn = turns.value.find((value) => value.key === item.turnKey)
      return turn
        ? generatePreview(
            item.turnKey,
            item,
            Number(turn.speakerKey),
            draftStore.currentIndex,
            false,
          )
        : Promise.resolve()
    }),
  )
  await refreshPreviewJobs()
}

async function removeTurnPreview(turnKey: number): Promise<void> {
  const state = previewStates.value[turnKey]
  const next = { ...previewStates.value }
  delete next[turnKey]
  replacePreviewBucket(next)
  await Promise.allSettled(
    previewJobIds(state).map((jobId) => deleteAudioPreview(jobId)),
  )
}

function previewJobIds(state?: TurnPreviewState): number[] {
  if (!state) return []
  return [
    ...new Set([
      ...state.segments.flatMap((segment) =>
        [segment.pendingJobId, segment.readyJobId].filter(
          (jobId): jobId is number => typeof jobId === 'number',
        ),
      ),
      ...(state.generated?.segments.map((segment) => segment.jobId) ?? []),
    ]),
  ]
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
    const sourceAudioId = Number(route.query.fromAudio)
    const creationDraftRequest = Number.isInteger(sourceAudioId) && sourceAudioId > 0
      ? getAudioCreationDraft(sourceAudioId)
      : Promise.resolve(null)
    const [voiceResponse, tagResponse, creationDraft] = await Promise.all([
      listVoices({ language: locale.value }),
      listAudioCreationTags(locale.value),
      creationDraftRequest,
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
    if (batchMode.value && draftStore.activeDraft) {
      applyDraft(draftStore.activeDraft)
    } else if (creationDraft) {
      applyCreationDraft(creationDraft)
    } else {
      if (speakers.value.length === 0) speakers.value = [newSpeaker(voiceId)]
      if (turns.value.length === 0) turns.value = [newTurn(speakers.value[0]?.key)]
    }
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Creation options could not be loaded')
  } finally {
    loadingOptions.value = false
  }
}

async function submit(): Promise<void> {
  formError.value = ''
  if (batchMode.value) {
    saveActiveDraft()
    if (!allBatchPreviewsReady.value) {
      await generateAllDraftPreviews()
      return
    }
    if (batchHasUnpublishedTurnChanges.value) {
      discardChangesDialogOpen.value = true
      return
    }
    await publishDraftBatchFromPreviews()
    return
  }
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

function validateDraft(draft: ListeningDraft): string | null {
  if (!draft.title.trim()) return t('Enter a title')
  if (
    draft.utterances.length === 0 ||
    draft.utterances.some(
      (item) =>
        !item.speakerDisplayName.trim() ||
        !item.text.trim() ||
        !Number.isInteger(item.voiceId) ||
        item.voiceId < 1,
    )
  ) {
    return t('Select a speaker and enter text for every item')
  }
  const speakerVoices = new Map<string, number>()
  for (const utterance of draft.utterances) {
    const speaker = utterance.speakerDisplayName.trim().normalize('NFKC').toLocaleLowerCase()
    const existingVoice = speakerVoices.get(speaker)
    if (existingVoice !== undefined && existingVoice !== utterance.voiceId) {
      return t('Complete each speaker with a unique name and voice')
    }
    speakerVoices.set(speaker, utterance.voiceId)
  }
  if (draft.questionType !== 'monologue' && speakerVoices.size < 2) {
    return t('Dialogue types require at least two speakers')
  }
  if (draft.questionType === 'monologue' && speakerVoices.size !== 1) {
    return t('Monologue requires one speaker')
  }
  if (
    draft.questions.some(
      (question) =>
        !question.prompt.trim() ||
        question.correctAnswers.length === 0 ||
        question.incorrectAnswers.length === 0 ||
        [...question.correctAnswers, ...question.incorrectAnswers].some(
          (answer) => !answer.trim(),
        ),
    )
  ) {
    return t('Complete every question and answer')
  }
  return null
}

function validateDraftForPublishing(draft: ListeningDraft): string | null {
  if (!draft.title.trim()) return t('Enter a title')
  if (
    draft.questions.some(
      (question) =>
        !question.prompt.trim() ||
        question.correctAnswers.length === 0 ||
        question.incorrectAnswers.length === 0 ||
        [...question.correctAnswers, ...question.incorrectAnswers].some(
          (answer) => !answer.trim(),
        ),
    )
  ) {
    return t('Complete every question and answer')
  }
  return null
}

function normalizeDraftQuestions(draft: ListeningDraft): AudioQuestionInput[] {
  return draft.questions.map((question) => ({
    prompt: question.prompt.trim(),
    correctAnswers: question.correctAnswers.map((answer) => answer.trim()),
    incorrectAnswers: question.incorrectAnswers.map((answer) => answer.trim()),
  }))
}

async function generateAllDraftPreviews(): Promise<void> {
  batchFailures.value = []
  const invalid = draftStore.drafts
    .map((draft, index) => ({ index, error: validateDraft(draft) }))
    .find((item) => item.error)
  if (invalid?.error) {
    draftStore.currentIndex = invalid.index
    applyDraft(draftStore.drafts[invalid.index]!)
    formError.value = invalid.error
    return
  }

  publishing.value = true
  try {
    const submissions: Promise<void>[] = []
    for (const [index, draft] of draftStore.drafts.entries()) {
      for (const [turnIndex, utterance] of draft.utterances.entries()) {
        if (batchPreviewStates.value[index]?.[turnIndex + 1]?.generated) continue
        submissions.push(
          generatePreview(
            turnIndex + 1,
            {
              voiceId: utterance.voiceId,
              speakerDisplayName: utterance.speakerDisplayName.trim(),
              text: utterance.text.trim(),
            },
            utterance.speakerKey,
            index,
            false,
          ),
        )
      }
    }
    await Promise.all(submissions)
    await refreshPreviewJobs()
  } finally {
    publishing.value = false
  }
}

async function publishDraftBatchFromPreviews(): Promise<void> {
  batchFailures.value = []
  const invalid = draftStore.drafts
    .map((draft, index) => ({ index, error: validateDraftForPublishing(draft) }))
    .find((item) => item.error)
  if (invalid?.error) {
    draftStore.currentIndex = invalid.index
    applyDraft(draftStore.drafts[invalid.index]!)
    formError.value = invalid.error
    return
  }

  publishing.value = true
  const succeeded = new Set<number>()
  try {
    for (const [index, draft] of draftStore.drafts.entries()) {
      const states = batchPreviewStates.value[index] ?? {}
      const utterances = draft.utterances.map((utterance, turnIndex) => {
        const generated = states[turnIndex + 1]?.generated
        const current = {
          voiceId: utterance.voiceId,
          speakerDisplayName: utterance.speakerDisplayName.trim(),
          text: utterance.text.trim(),
        }
        return generated
          ? {
              ...generatedPreviewPayload(generated),
              voiceId:
                generated.source === 'upload'
                  ? current.voiceId
                  : generated.content.voiceId,
              speakerDisplayName:
                generated.source === 'upload'
                  ? current.speakerDisplayName
                  : utterance.speakerKey === generated.speakerKey
                    ? current.speakerDisplayName
                    : generated.content.speakerDisplayName,
              text:
                generated.source === 'upload'
                  ? current.text
                  : generated.content.text,
            }
          : null
      })
      if (utterances.some((item) => item === null)) continue
      try {
        const audio = await publishAudioFromPreviews({
          title: draft.title.trim(),
          utterances: utterances as NonNullable<(typeof utterances)[number]>[],
          tagIds: draft.tagIds,
          visibility: 'public',
          questions: normalizeDraftQuestions(draft),
        })
        batchResults.value.push({ title: draft.title, audioId: audio.id })
        succeeded.add(index)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : t('Audio could not be published')
        batchFailures.value.push(`${draft.title}: ${message}`)
      }
    }

    const retainedPreviewStates: Record<number, Record<number, TurnPreviewState>> = {}
    const retainedPrompts: Record<number, string> = {}
    const retainedRevisionErrors: Record<number, string> = {}
    const retainedRevisionHistories: Record<number, DraftRevisionHistory> = {}
    let retainedIndex = 0
    for (const [index] of draftStore.drafts.entries()) {
      if (succeeded.has(index)) continue
      retainedPreviewStates[retainedIndex] = batchPreviewStates.value[index] ?? {}
      if (aiPrompts.value[index]) retainedPrompts[retainedIndex] = aiPrompts.value[index]!
      if (aiRevisionErrors.value[index]) {
        retainedRevisionErrors[retainedIndex] = aiRevisionErrors.value[index]!
      }
      if (draftRevisionHistories.value[index]) {
        retainedRevisionHistories[retainedIndex] = draftRevisionHistories.value[index]!
      }
      retainedIndex += 1
    }
    for (const index of [...succeeded].sort((a, b) => b - a)) {
      draftStore.removeDraft(index)
    }
    batchPreviewStates.value = retainedPreviewStates
    aiPrompts.value = retainedPrompts
    aiRevisionErrors.value = retainedRevisionErrors
    draftRevisionHistories.value = retainedRevisionHistories
    if (draftStore.drafts.length > 0) {
      draftStore.currentIndex = 0
      applyDraft(draftStore.drafts[0]!)
      formError.value = t('{count} drafts could not be created', {
        count: batchFailures.value.length,
      })
    }
  } finally {
    publishing.value = false
  }
}

async function publishGeneratedAudio(): Promise<void> {
  formError.value = ''
  const normalizedTitle = title.value.trim()
  if (!normalizedTitle) {
    formError.value = t('Enter a title')
    return
  }
  const normalizedQuestionValues = normalizedQuestions()
  if (!normalizedQuestionValues) return
  const currentContent = validateContent()
  if (!currentContent) return
  const contentByTurnKey = new Map(
    currentContent.map((content) => [content.turnKey, content]),
  )
  const utterances = turns.value.map((turn) => {
    const generated = previewStates.value[turn.key]?.generated
    const speaker = speakers.value.find((item) => item.key === turn.speakerKey)
    const current = contentByTurnKey.get(turn.key)
    return generated
      ? {
          ...generatedPreviewPayload(generated),
          voiceId:
            generated.source === 'upload' && current
              ? current.voiceId
              : generated.content.voiceId,
          speakerDisplayName:
            generated.source === 'upload' && current
              ? current.speakerDisplayName
              : Number(turn.speakerKey) === generated.speakerKey
                ? speaker?.name.trim() || generated.content.speakerDisplayName
                : generated.content.speakerDisplayName,
          text:
            generated.source === 'upload' && current
              ? current.text
              : generated.content.text,
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
      questions: normalizedQuestionValues,
    })
    publishedAudioId.value = audio.id
    standalonePreviewStates.value = {}
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Audio could not be published')
  } finally {
    publishing.value = false
  }
}

function generatedPreviewPayload(generated: GeneratedTurnPreview): {
  previewJobId?: number
  segments?: Array<{ previewJobId: number; text: string }>
} {
  if (generated.source === 'upload') {
    return { previewJobId: generated.segments[0]!.jobId }
  }
  return {
    segments: generated.segments.map((segment) => ({
      previewJobId: segment.jobId,
      text: segment.text,
    })),
  }
}

async function confirmDiscardChangesAndPublish(): Promise<void> {
  discardChangesDialogOpen.value = false
  if (batchMode.value) {
    await publishDraftBatchFromPreviews()
  } else {
    await publishGeneratedAudio()
  }
}

function startAnother(): void {
  publishedAudioId.value = null
  title.value = ''
  speakers.value = []
  speakers.value = [newSpeaker()]
  turns.value = [newTurn(speakers.value[0]?.key)]
  selectedTagIds.value = []
  questions.value = []
  visibility.value = 'public'
  formError.value = ''
  discardChangesDialogOpen.value = false
  batchResults.value = []
  batchFailures.value = []
  aiEditorOpen.value = false
  aiPrompts.value = {}
  aiRevisionErrors.value = {}
  draftRevisionHistories.value = {}
}

async function cleanupPreviews(): Promise<void> {
  clearTimeout(previewPollTimer)
  const jobIds = [
    ...new Set(
      previewStateEntries()
        .flatMap(({ state }) => previewJobIds(state)),
    ),
  ]
  standalonePreviewStates.value = {}
  batchPreviewStates.value = {}
  await Promise.allSettled(jobIds.map((jobId) => deleteAudioPreview(jobId)))
}

onMounted(() => {
  void loadOptions()
})
onBeforeRouteLeave(async () => {
  if (batchMode.value) saveActiveDraft()
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

    <div v-if="publishedAudioId || (batchResults.length > 0 && draftStore.drafts.length === 0)" class="mt-6 rounded-lg border border-line bg-surface px-5 py-9 shadow-panel">
      <p class="text-base font-semibold text-success">{{ t('Audio is ready') }}</p>
      <ul v-if="batchResults.length" class="mt-5 divide-y divide-line border-y border-line">
        <li v-for="result in batchResults" :key="result.audioId" class="flex items-center justify-between gap-4 py-3">
          <span class="min-w-0 truncate text-sm font-medium">{{ result.title }}</span>
          <RouterLink :to="`/audio/${result.audioId}`" class="shrink-0 text-sm font-medium text-accent hover:underline">{{ t('View audio') }}</RouterLink>
        </li>
      </ul>
      <div class="mt-5 flex flex-wrap gap-3">
        <RouterLink
          v-if="publishedAudioId"
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
      <div v-if="batchMode" class="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-canvas px-5 py-3">
        <div class="flex flex-wrap items-center gap-3">
          <p class="text-sm font-medium">{{ t('Draft {current} of {total}', { current: draftStore.currentIndex + 1, total: draftStore.drafts.length }) }}</p>
          <button
            type="button"
            class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
            :aria-expanded="aiEditorOpen"
            @click="aiEditorOpen = !aiEditorOpen"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="m12 3 1.3 4.2L17.5 8.5l-4.2 1.3L12 14l-1.3-4.2-4.2-1.3 4.2-1.3L12 3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
              <path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
            </svg>
            {{ t('AI modify') }}
          </button>
        </div>
        <div class="flex items-center gap-2">
          <button type="button" class="flex h-9 w-9 items-center justify-center border border-line bg-surface disabled:opacity-30" :disabled="draftStore.currentIndex === 0 || revisingDraftIndex !== null" :title="t('Previous')" @click="selectDraft(draftStore.currentIndex - 1)">
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" /></svg>
          </button>
          <button type="button" class="flex h-9 w-9 items-center justify-center border border-line bg-surface disabled:opacity-30" :disabled="draftStore.currentIndex >= draftStore.drafts.length - 1 || revisingDraftIndex !== null" :title="t('Next')" @click="selectDraft(draftStore.currentIndex + 1)">
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" /></svg>
          </button>
        </div>
      </div>
      <div v-if="batchMode && aiEditorOpen" class="border-b border-line bg-canvas px-5 py-5">
        <label for="ai-revision-prompt" class="mb-1 block text-sm font-medium">{{ t('Modification prompt') }}</label>
        <textarea
          id="ai-revision-prompt"
          v-model="aiPrompts[draftStore.currentIndex]"
          rows="4"
          maxlength="4000"
          class="w-full resize-y border border-line bg-surface px-3 py-2 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        />
        <div
          v-if="revisingDraftIndex === draftStore.currentIndex"
          class="mt-3"
          role="progressbar"
          :aria-label="t('AI revision progress')"
        >
          <div class="mb-1 flex items-center justify-between gap-3 text-xs text-muted">
            <span>{{ t('Modifying') }}</span>
            <span>{{ t('Waiting for AI response') }}</span>
          </div>
          <div class="h-2 overflow-hidden bg-raised">
            <span class="ai-revision-progress block h-full bg-accent" aria-hidden="true" />
          </div>
        </div>
        <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p v-if="aiRevisionErrors[draftStore.currentIndex]" class="text-sm text-danger" role="alert">{{ aiRevisionErrors[draftStore.currentIndex] }}</p>
          <span v-else />
          <div class="flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="h-9 border border-line bg-surface px-3 text-sm font-medium disabled:opacity-30"
              :disabled="revisionHistory().past.length === 0 || revisingDraftIndex !== null"
              @click="undoDraftRevision"
            >
              {{ t('Undo') }}
            </button>
            <button
              type="button"
              class="h-9 border border-line bg-surface px-3 text-sm font-medium disabled:opacity-30"
              :disabled="revisionHistory().future.length === 0 || revisingDraftIndex !== null"
              @click="redoDraftRevision"
            >
              {{ t('Redo') }}
            </button>
            <button
              type="button"
              class="h-9 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
              :disabled="!(aiPrompts[draftStore.currentIndex]?.trim()) || revisingDraftIndex !== null"
              @click="reviseActiveDraft"
            >
              {{ revisingDraftIndex === draftStore.currentIndex ? t('Modifying') : t('Submit modification') }}
            </button>
          </div>
        </div>
      </div>
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
        :can-upload="auth.isAdmin"
        @generate="generateTurnPreview"
        @regenerate-segment="regeneratePreviewSegment"
        @upload="uploadTurnPreview"
        @remove="removeTurnPreview"
      />

      <div class="min-w-0 border-b border-line px-5 py-6">
        <h2 class="mb-5 text-sm font-semibold">{{ t('Tags') }}</h2>
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
      </div>

      <AudioQuestionsEditor v-model="questions" />

      <div class="grid min-w-0 gap-6 px-5 py-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div></div>
        <div class="flex flex-col gap-6">
          <label class="flex items-start gap-3">
            <input type="checkbox" class="mt-0.5 h-4 w-4 accent-accent" :checked="visibility === 'public'" @change="visibility = ($event.target as HTMLInputElement).checked ? 'public' : 'private'" />
            <span class="text-sm font-medium">{{ t('Publish when ready') }}</span>
          </label>
          <div>
            <p v-if="formError" role="alert" class="mb-3 break-words text-sm text-danger">{{ formError }}</p>
            <button type="submit" :disabled="publishing || previewGenerationActive || revisingDraftIndex !== null || loadingOptions || voices.length === 0" class="inline-flex h-10 w-full items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50">
              <svg v-if="batchMode ? allBatchPreviewsReady : allPreviewsReady" viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 12.5 9.5 17 19 7" stroke="currentColor" stroke-width="2" /></svg>
              <svg v-else viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M8 5v14l11-7Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" /></svg>
              {{ publishing ? t('Submitting') : batchMode ? allBatchPreviewsReady ? t('Publish all drafts') : t('Generate all draft audio') : allPreviewsReady ? t('Publish') : t('Generate audio') }}
            </button>
            <ul v-if="batchFailures.length" class="mt-3 space-y-1 text-sm text-danger"><li v-for="failure in batchFailures" :key="failure">{{ failure }}</li></ul>
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
      :title="t(batchMode ? 'Publish generated drafts?' : 'Publish generated audio?')"
      :busy="publishing"
      confirm-label="Publish"
      @close="discardChangesDialogOpen = false"
      @confirm="confirmDiscardChangesAndPublish"
    >
      {{ t(batchMode ? 'Changes made after preview generation will be discarded for affected drafts. The last generated audio will be published instead.' : 'Changes made after preview generation will be discarded. The last generated audio will be published instead.') }}
    </ConfirmDialog>
  </section>
</template>

<style scoped>
.ai-revision-progress {
  width: 36%;
  animation: ai-revision-progress 1.6s ease-in-out infinite;
}

@keyframes ai-revision-progress {
  0% {
    transform: translateX(-105%);
  }
  100% {
    transform: translateX(285%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ai-revision-progress {
    width: 100%;
    animation: none;
  }
}
</style>
