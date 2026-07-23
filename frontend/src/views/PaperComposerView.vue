<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createAssembly,
  createAssemblyPreview,
  createAssemblyTemplate,
  deleteAssemblyPreview,
  deleteAssemblyTemplate,
  listAssemblyTemplates,
  assemblyPreviewMediaPath,
  updateAssemblyTemplate,
  type AssemblySegmentInput,
  type AssemblySegmentType,
  type AssemblySmartMode,
  type AssemblyTemplate,
  type AssemblyTemplateWriteInput,
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
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import { useI18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

const PAGE_SIZE = 10
let nextKey = 1
type CreationTagType = 'topic' | 'category'
type SmartSilenceAssociation = '' | 'previous' | 'next'
type MoveDirection = 'up' | 'down'
const tagGroups: { label: string; type: CreationTagType }[] = [
  { label: 'Topics', type: 'topic' },
  { label: 'Categories', type: 'category' },
]

interface DraftSegment extends AssemblySegmentInput {
  key: number
  audio?: Audio
  commentEditing: boolean
  previewEndPosition?: number
}

interface PreviewTarget {
  segmentKey: number
  fromHere: boolean
  endIndex?: number
  fingerprint: string
}

interface PendingTemplateOverwrite {
  templateId: number
  existingTitle: string
  input: AssemblyTemplateWriteInput
}

const router = useRouter()
const auth = useAuthStore()
const { locale, t } = useI18n()
const title = ref('')
const visibility = ref<ResourceVisibility>('public')
const templates = ref<AssemblyTemplate[]>([])
const templateId = ref('')
const appliedTemplateId = ref('')
const pendingTemplateId = ref<string | null>(null)
const pendingTemplateOverwrite = ref<PendingTemplateOverwrite | null>(null)
const templateLoading = ref(false)
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
const segmentSelectionMode = ref(false)
const selectedSegmentKeys = ref<number[]>([])
const segmentList = ref<HTMLOListElement | null>(null)
const moveOptionsSegmentKey = ref<number | null>(null)
const moveOptionsDirection = ref<MoveDirection>('up')
const moveOptionsDistance = ref(1)
const moveOptionsAfterPosition = ref(0)
const loading = ref(true)
const submitting = ref(false)
const savingTemplate = ref(false)
const errorMessage = ref('')
const accepted = ref<{ audioId: number; jobId: number } | null>(null)
const job = ref<Job | null>(null)
const previewPlayer = ref<HTMLAudioElement | null>(null)
const previewJob = ref<Job | null>(null)
const currentPreviewJobId = ref<number | null>(null)
const pendingPreviewJobId = ref<number | null>(null)
const previewMediaUrl = ref('')
const previewBusy = ref(false)
const previewPlaying = ref(false)
const activePreview = ref<PreviewTarget | null>(null)
const pendingPreview = ref<PreviewTarget | null>(null)
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
  segments.value.reduce((totalSeconds, segment, index) => {
    if (segment.type === 'silence') {
      return totalSeconds + (segment.silenceMilliseconds ?? 0) / 1000
    }
    if (isQuestionCountSilence(segment)) {
      const associatedIndex = questionCountPlaceholderIndex(
        index,
        Boolean(segment.smartSilencePrevious),
      )
      const questionCount =
        associatedIndex === null
          ? 0
          : segments.value[associatedIndex]?.audio?.questions?.length ?? 0
      return totalSeconds + ((segment.silenceMilliseconds ?? 0) / 1000) * questionCount
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
    .filter((segment) => segment.includeText)
    .map((segment) =>
      segment.type === 'comment'
        ? segment.commentText?.trim() ?? ''
        : segment.audio?.text ?? '',
    )
    .filter(Boolean)
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
    type,
    repeatCount: 1,
    repeatIntervalMilliseconds: 1000,
    includeText: true,
    includeTopic: true,
    silenceMilliseconds: 0,
    smartMode: 'question_number',
    smartSilencePrevious: false,
    smartSilenceNext: false,
    commentEditing: false,
    ...values,
    key: nextKey++,
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

function selectTemplate(): void {
  if (!templateId.value) {
    appliedTemplateId.value = ''
    pendingTemplateId.value = null
    return
  }
  if (segments.value.length > 0) {
    pendingTemplateId.value = templateId.value
    return
  }
  void applyTemplate(templateId.value)
}

function closeTemplateReplacement(): void {
  templateId.value = appliedTemplateId.value
  pendingTemplateId.value = null
}

function confirmTemplateReplacement(): void {
  const selectedTemplateId = pendingTemplateId.value
  pendingTemplateId.value = null
  if (selectedTemplateId) void applyTemplate(selectedTemplateId)
}

async function applyTemplate(selectedTemplateId: string): Promise<void> {
  const template = templates.value.find(
    (item) => String(item.id) === selectedTemplateId,
  )
  if (!template) {
    templateId.value = appliedTemplateId.value
    return
  }
  templateLoading.value = true
  errorMessage.value = ''
  const next: DraftSegment[] = []
  try {
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
    selectedSegmentKeys.value = []
    activePlaceholder.value = null
    moveOptionsSegmentKey.value = null
    resetPrefilledTags()
    for (const segment of next) {
      if (segment.audio && segment.includeTopic) addAudioTopics(segment.audio)
    }
    appliedTemplateId.value = selectedTemplateId
  } finally {
    templateLoading.value = false
  }
}

function addAudio(audio: Audio): void {
  if (activePlaceholder.value !== null) {
    const segment = segments.value[activePlaceholder.value]
    if (segment?.type === 'placeholder') {
      if (segment.includeTopic && segment.audio) removeSegmentAudioTopics(segment)
      segment.audio = audio
      segment.audioId = audio.id
      if (segment.includeTopic) addAudioTopics(audio)
      activePlaceholder.value = null
      return
    }
  }
  appendSegments(draft('audio', { audio, audioId: audio.id }))
  addAudioTopics(audio)
}

function appendSegments(...items: DraftSegment[]): void {
  if (items.length === 0) return
  segments.value.push(...items)
  void nextTick(() => {
    const list = segmentList.value
    if (list) list.scrollTop = list.scrollHeight
  })
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

function removeSegmentAudioTopics(segment: DraftSegment): void {
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

function setSegmentTopic(segment: DraftSegment, selected: boolean): void {
  segment.includeTopic = selected
  if (selected && segment.audio) {
    addAudioTopics(segment.audio)
    return
  }
  removeSegmentAudioTopics(segment)
}

function clearPlaceholderAudio(segment: DraftSegment, index: number): void {
  if (segment.type !== 'placeholder') return
  if (segment.includeTopic) removeSegmentAudioTopics(segment)
  segment.audio = undefined
  segment.audioId = undefined
  if (activePlaceholder.value === index) activePlaceholder.value = null
}

function addSilence(): void {
  appendSegments(draft('silence', { silenceMilliseconds: 5000 }))
}

function addComment(): void {
  appendSegments(
    draft('comment', {
      commentText: '',
      commentEditing: true,
      includeText: true,
      includeTopic: false,
    }),
  )
}

function confirmComment(segment: DraftSegment): void {
  const text = segment.commentText?.trim()
  if (!text) return
  segment.commentText = text
  segment.commentEditing = false
}

function seconds(milliseconds: number | undefined): number {
  return (milliseconds ?? 0) / 1000
}

function millisecondsFromInput(event: Event): number {
  const value = (event.target as HTMLInputElement).valueAsNumber
  return Number.isFinite(value) ? Math.round(value * 1000) : 0
}

function addPlaceholder(): void {
  appendSegments(draft('placeholder', { suggestedQuery: '' }))
}

function addSmart(): void {
  appendSegments(draft('smart', { includeText: false, includeTopic: false }))
}

function setSmartMode(segment: DraftSegment, mode: AssemblySmartMode): void {
  segment.smartMode = mode
  segment.smartSilencePrevious = false
  segment.smartSilenceNext = false
  segment.silenceMilliseconds = mode === 'question_count_silence' ? 5000 : 0
}

function smartSilenceAssociation(segment: DraftSegment): SmartSilenceAssociation {
  if (segment.smartSilencePrevious && !segment.smartSilenceNext) return 'previous'
  if (segment.smartSilenceNext && !segment.smartSilencePrevious) return 'next'
  return ''
}

function setSmartSilenceAssociation(
  segment: DraftSegment,
  association: SmartSilenceAssociation,
): void {
  segment.smartSilencePrevious = association === 'previous'
  segment.smartSilenceNext = association === 'next'
}

function selectPlaceholder(index: number): void {
  activePlaceholder.value = index
  query.value = segments.value[index]?.suggestedQuery ?? ''
  void loadPage(true)
}

function cancelPlaceholderSelection(): void {
  activePlaceholder.value = null
}

function move(index: number, offset: -1 | 1): void {
  const target = index + offset
  moveToIndex(index, target)
}

function moveToIndex(index: number, target: number): boolean {
  if (
    index < 0 ||
    index >= segments.value.length ||
    target < 0 ||
    target >= segments.value.length ||
    index === target
  ) {
    return false
  }
  const next = [...segments.value]
  const [item] = next.splice(index, 1)
  if (!item) return false
  next.splice(target, 0, item)
  segments.value = next
  activePlaceholder.value = null
  return true
}

function toggleMoveOptions(index: number): void {
  const segment = segments.value[index]
  if (!segment) return
  if (moveOptionsSegmentKey.value === segment.key) {
    moveOptionsSegmentKey.value = null
    return
  }
  moveOptionsSegmentKey.value = segment.key
  moveOptionsDirection.value = 'up'
  moveOptionsDistance.value = 1
  moveOptionsAfterPosition.value = 0
}

function dismissMoveOptions(event: PointerEvent): void {
  if (moveOptionsSegmentKey.value === null) return
  if (
    !(event.target instanceof Element) ||
    !event.target.closest('[data-move-options]')
  ) {
    moveOptionsSegmentKey.value = null
  }
}

function moveByOptions(index: number): void {
  const distance = Math.trunc(moveOptionsDistance.value)
  if (!Number.isFinite(distance) || distance < 1) return
  const offset = moveOptionsDirection.value === 'up' ? -distance : distance
  if (moveToIndex(index, index + offset)) {
    moveOptionsSegmentKey.value = null
  }
}

function moveAfterPosition(index: number): void {
  const afterPosition = Math.trunc(moveOptionsAfterPosition.value)
  if (
    !Number.isFinite(afterPosition) ||
    afterPosition < 0 ||
    afterPosition > segments.value.length
  ) {
    return
  }
  const target = afterPosition > index ? afterPosition - 1 : afterPosition
  if (moveToIndex(index, target)) {
    moveOptionsSegmentKey.value = null
  }
}

function remove(index: number): void {
  const [removed] = segments.value.splice(index, 1)
  if (removed) {
    selectedSegmentKeys.value = selectedSegmentKeys.value.filter(
      (key) => key !== removed.key,
    )
    if (moveOptionsSegmentKey.value === removed.key) {
      moveOptionsSegmentKey.value = null
    }
  }
  activePlaceholder.value = null
}

function toggleSegmentSelectionMode(): void {
  segmentSelectionMode.value = !segmentSelectionMode.value
  selectedSegmentKeys.value = []
  moveOptionsSegmentKey.value = null
}

function setSegmentSelected(segmentKey: number, selected: boolean): void {
  if (selected) {
    if (!selectedSegmentKeys.value.includes(segmentKey)) {
      selectedSegmentKeys.value = [...selectedSegmentKeys.value, segmentKey]
    }
    return
  }
  selectedSegmentKeys.value = selectedSegmentKeys.value.filter(
    (key) => key !== segmentKey,
  )
}

function deleteSelectedSegments(): void {
  const selected = new Set(selectedSegmentKeys.value)
  if (selected.size === 0) return
  segments.value = segments.value.filter((segment) => !selected.has(segment.key))
  selectedSegmentKeys.value = []
  activePlaceholder.value = null
  moveOptionsSegmentKey.value = null
}

function copySelectedSegments(): void {
  const selected = new Set(selectedSegmentKeys.value)
  if (selected.size === 0) return
  const copies = segments.value
    .filter((segment) => selected.has(segment.key))
    .map((segment) => draft(segment.type, segment))
  appendSegments(...copies)
  selectedSegmentKeys.value = []
}

function canPlaySegment(segment: DraftSegment, index: number): boolean {
  if (
    segment.type === 'silence' ||
    segment.type === 'comment' ||
    isQuestionCountSilence(segment)
  ) {
    return false
  }
  if (segment.type === 'audio') return Boolean(segment.audioId)
  if (segment.type === 'placeholder') return Boolean(segment.audioId)
  const placeholderIndex = questionNumberPlaceholderIndex(index)
  return placeholderIndex !== null && Boolean(segments.value[placeholderIndex]?.audioId)
}

function setPreviewEndPosition(segment: DraftSegment, event: Event): void {
  const input = event.target as HTMLInputElement
  segment.previewEndPosition = input.value === '' ? undefined : input.valueAsNumber
}

function isPreviewEndPositionValid(segment: DraftSegment, index: number): boolean {
  const position = segment.previewEndPosition
  return (
    position === undefined ||
    (Number.isInteger(position) && position >= index + 1 && position <= segments.value.length)
  )
}

function previewEndIndex(segment: DraftSegment, index: number): number | undefined {
  return isPreviewEndPositionValid(segment, index) && segment.previewEndPosition !== undefined
    ? segment.previewEndPosition - 1
    : undefined
}

function previewTargetMatches(
  target: PreviewTarget | null,
  segment: DraftSegment,
  index: number,
  fromHere: boolean,
): boolean {
  if (!target || (fromHere && !isPreviewEndPositionValid(segment, index))) return false
  const endIndex = fromHere ? previewEndIndex(segment, index) : index
  return (
    target.segmentKey === segment.key &&
    target.fromHere === fromHere &&
    target.endIndex === endIndex &&
    target.fingerprint === segmentFingerprint.value
  )
}

function isQuestionCountSilence(segment: DraftSegment): boolean {
  return segment.type === 'smart' && segment.smartMode === 'question_count_silence'
}

function questionNumberPlaceholderIndex(index: number): number | null {
  for (let position = index + 1; position < segments.value.length; position += 1) {
    const item = segments.value[position]!
    if (item.type === 'placeholder') return position
    if (
      item.type === 'silence' ||
      item.type === 'comment' ||
      isQuestionCountSilence(item)
    ) continue
    return null
  }
  return null
}

function questionCountPlaceholderIndex(index: number, previous: boolean): number | null {
  const direction = previous ? -1 : 1
  for (
    let position = index + direction;
    position >= 0 && position < segments.value.length;
    position += direction
  ) {
    const item = segments.value[position]!
    if (item.type === 'comment') continue
    return item.type === 'placeholder' ? position : null
  }
  return null
}

function segmentInput(segment: DraftSegment): AssemblySegmentInput {
  return {
    type: segment.type,
    audioId: segment.audioId,
    suggestedQuery: segment.suggestedQuery || undefined,
    commentText:
      segment.type === 'comment' ? segment.commentText?.trim() : undefined,
    silenceMilliseconds:
      segment.type === 'silence' || isQuestionCountSilence(segment)
        ? segment.silenceMilliseconds
        : 0,
    smartMode: segment.smartMode,
    smartSilencePrevious: segment.smartSilencePrevious,
    smartSilenceNext: segment.smartSilenceNext,
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
    if (item.type === 'comment' && !item.commentText?.trim()) {
      return t('Enter text for every comment segment')
    }
    if ((item.type === 'audio' || item.type === 'placeholder') && !item.audioId) {
      return t('Fill every placeholder before publishing')
    }
    if (item.type === 'smart' && item.smartMode === 'question_number') {
      if (questionNumberPlaceholderIndex(index) === null) {
        return t('Question-number audio requires a following placeholder with only silence or comments between')
      }
    }
    if (isQuestionCountSilence(item)) {
      if (item.smartSilencePrevious === item.smartSilenceNext) {
        return t('Select exactly one placeholder for question-count silence')
      }
      if (
        item.smartSilencePrevious &&
        questionCountPlaceholderIndex(index, true) === null
      ) {
        return t('The previous non-comment segment must be a placeholder')
      }
      if (
        item.smartSilenceNext &&
        questionCountPlaceholderIndex(index, false) === null
      ) {
        return t('The next non-comment segment must be a placeholder')
      }
    }
  }
  return null
}

async function playPreview(index: number, fromHere: boolean): Promise<void> {
  const segment = segments.value[index]
  if (
    !segment ||
    !canPlaySegment(segment, index) ||
    (fromHere && !isPreviewEndPositionValid(segment, index))
  ) return
  const fingerprint = segmentFingerprint.value
  const endIndex = fromHere ? previewEndIndex(segment, index) : index
  const samePreview = previewTargetMatches(
    activePreview.value,
    segment,
    index,
    fromHere,
  )
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
  await cancelPendingPreview(false, true)
  if (requestVersion !== previewRequestVersion) return
  pendingPreview.value = { segmentKey: segment.key, fromHere, endIndex, fingerprint }
  errorMessage.value = ''
  try {
    const acceptedPreview = await createAssemblyPreview({
      segments: segments.value.map(segmentInput),
      startIndex: index,
      endIndex,
    })
    if (requestVersion !== previewRequestVersion) {
      void deleteAssemblyPreview(acceptedPreview.jobId).catch(() => undefined)
      return
    }
    pendingPreviewJobId.value = acceptedPreview.jobId
    await refreshPreviewJob(requestVersion)
  } catch (error) {
    if (requestVersion === previewRequestVersion) {
      previewBusy.value = false
      errorMessage.value =
        error instanceof ApiError ? error.message : t('Playback preview could not be created')
      pendingPreview.value = null
    }
  }
}

async function refreshPreviewJob(requestVersion: number): Promise<void> {
  const jobId = pendingPreviewJobId.value
  if (jobId === null || requestVersion !== previewRequestVersion) return
  try {
    previewJob.value = await getJob(jobId)
    if (requestVersion !== previewRequestVersion) return
    if (previewJob.value.status === 'succeeded') {
      const completedPreview = pendingPreview.value
      const previousJobId = currentPreviewJobId.value
      previewPlayer.value?.pause()
      previewPlaying.value = false
      currentPreviewJobId.value = jobId
      pendingPreviewJobId.value = null
      activePreview.value = completedPreview
      pendingPreview.value = null
      previewJob.value = null
      previewBusy.value = false
      previewMediaUrl.value = assemblyPreviewMediaPath(jobId)
      await nextTick()
      previewPlayer.value?.load()
      try {
        await previewPlayer.value?.play()
      } catch {
        errorMessage.value = t('Use the audio controls to start playback')
      }
      if (previousJobId !== null) {
        void deleteAssemblyPreview(previousJobId).catch(() => undefined)
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
    pendingPreview.value = null
    pendingPreviewJobId.value = null
    errorMessage.value =
      previewJob.value.errorSummary || t('Playback preview could not be created')
    void deleteAssemblyPreview(jobId).catch(() => undefined)
  } catch (error) {
    previewBusy.value = false
    pendingPreview.value = null
    pendingPreviewJobId.value = null
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Playback status could not be loaded')
    void deleteAssemblyPreview(jobId).catch(() => undefined)
  }
}

async function cancelPendingPreview(
  invalidate = true,
  preserveBusy = false,
): Promise<void> {
  if (invalidate) previewRequestVersion += 1
  if (previewPollTimer !== undefined) window.clearTimeout(previewPollTimer)
  previewPollTimer = undefined
  previewJob.value = null
  if (!preserveBusy) previewBusy.value = false
  pendingPreview.value = null
  const jobId = pendingPreviewJobId.value
  pendingPreviewJobId.value = null
  if (jobId !== null) {
    await deleteAssemblyPreview(jobId).catch(() => undefined)
  }
}

async function cleanupPreviews(): Promise<void> {
  previewRequestVersion += 1
  if (previewPollTimer !== undefined) window.clearTimeout(previewPollTimer)
  previewPollTimer = undefined
  previewPlayer.value?.pause()
  previewPlaying.value = false
  previewMediaUrl.value = ''
  previewJob.value = null
  previewBusy.value = false
  activePreview.value = null
  pendingPreview.value = null
  const jobIds = [currentPreviewJobId.value, pendingPreviewJobId.value].filter(
    (jobId): jobId is number => jobId !== null,
  )
  currentPreviewJobId.value = null
  pendingPreviewJobId.value = null
  await Promise.all(
    [...new Set(jobIds)].map((jobId) =>
      deleteAssemblyPreview(jobId).catch(() => undefined),
    ),
  )
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
    await cleanupPreviews()
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
  const hasEmptyComment = segments.value.some(
    (segment) => segment.type === 'comment' && !segment.commentText?.trim(),
  )
  if (hasEmptyComment) {
    errorMessage.value = t('Enter text for every comment segment')
    return
  }
  const input: AssemblyTemplateWriteInput = {
    title: templateTitle.value.trim(),
    segments: segments.value.map((segment) => {
      const item = segmentInput(segment)
      if (item.type === 'placeholder') delete item.audioId
      return item
    }),
  }
  savingTemplate.value = true
  errorMessage.value = ''
  try {
    const created = await createAssemblyTemplate(input)
    finishTemplateSave(created, true)
  } catch (error) {
    const conflict = templateConflict(error)
    if (conflict) {
      pendingTemplateOverwrite.value = { ...conflict, input }
    } else {
      errorMessage.value = error instanceof ApiError ? error.message : t('Template could not be saved')
    }
  } finally {
    savingTemplate.value = false
  }
}

function templateConflict(
  error: unknown,
): Omit<PendingTemplateOverwrite, 'input'> | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  if (typeof error.details !== 'object' || error.details === null) return null
  const details = error.details as Record<string, unknown>
  if (!Number.isInteger(details.templateId) || Number(details.templateId) < 1) return null
  return {
    templateId: Number(details.templateId),
    existingTitle:
      typeof details.title === 'string' ? details.title : templateTitle.value.trim(),
  }
}

function finishTemplateSave(template: AssemblyTemplate, created: boolean): void {
  const exists = templates.value.some((item) => item.id === template.id)
  templates.value = created || !exists
    ? [template, ...templates.value]
    : templates.value.map((item) => (item.id === template.id ? template : item))
  templateId.value = String(template.id)
  appliedTemplateId.value = templateId.value
  templateTitle.value = ''
  pendingTemplateOverwrite.value = null
}

function closeTemplateOverwrite(): void {
  if (!savingTemplate.value) pendingTemplateOverwrite.value = null
}

async function confirmTemplateOverwrite(): Promise<void> {
  const pending = pendingTemplateOverwrite.value
  if (!pending || savingTemplate.value) return
  savingTemplate.value = true
  errorMessage.value = ''
  try {
    const updated = await updateAssemblyTemplate(pending.templateId, pending.input)
    finishTemplateSave(updated, false)
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
  appliedTemplateId.value = ''
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
  document.addEventListener('pointerdown', dismissMoveOptions)
  void Promise.all([loadOptions(), loadPage()])
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', dismissMoveOptions)
  stopPublishPolling()
  void cleanupPreviews()
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
          <select v-model="templateId" :disabled="templateLoading || pendingTemplateId !== null" class="mt-2 h-10 w-full border border-line bg-surface px-3 font-normal disabled:opacity-50" @change="selectTemplate">
            <option value="">{{ t('No template') }}</option>
            <option v-for="item in templates" :key="item.id" :value="String(item.id)">{{ item.title }}</option>
          </select>
          <span v-if="templateLoading" class="mt-2 block text-xs font-normal text-muted">{{ t('Loading template') }}</span>
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
        <section aria-labelledby="audio-source-title" class="order-2 min-w-0 xl:order-1">
          <div class="mb-4 flex items-end justify-between gap-3">
            <div>
              <h2 id="audio-source-title" class="text-base font-semibold">{{ t('Audio library') }}</h2>
              <p class="mt-1 text-sm text-muted">{{ t('{count} available', { count: total }) }}</p>
            </div>
          </div>
          <AudioSearchBox v-model="query" :tags="tagCatalog" :busy="loading" @submit="loadPage(true)" />
          <div class="mt-4 flex flex-wrap items-center justify-between gap-3 border-y border-line py-3 text-sm">
            <p>
              <span class="text-muted">{{ t('Add destination') }}:</span>
              <span class="ml-2 font-medium">
                {{ activePlaceholder === null ? t('End of segment list') : t('Placeholder at segment {position}', { position: activePlaceholder + 1 }) }}
              </span>
            </p>
            <button v-if="activePlaceholder !== null" type="button" class="font-medium text-accent" @click="cancelPlaceholderSelection">{{ t('Cancel placeholder selection') }}</button>
          </div>
          <ul class="max-h-[68vh] divide-y divide-line overflow-y-auto overscroll-contain border-b border-line">
            <li v-for="audio in candidates" :key="audio.id" class="grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div class="min-w-0">
                <p class="break-words text-sm font-semibold">{{ audio.title }}</p>
                <p class="mt-1 text-xs text-muted">{{ audio.questions?.length ?? 0 }} {{ t('Questions') }} · {{ audio.durationSeconds === null ? '' : duration(audio.durationSeconds) }}</p>
                <audio class="mt-2 h-8 w-full" controls preload="none" :src="audioMediaPath(audio.id)" />
              </div>
              <button type="button" class="h-9 border border-line px-3 text-sm font-medium hover:border-ink" @click="addAudio(audio)">{{ activePlaceholder === null ? t('Add to end') : t('Fill this placeholder') }}</button>
            </li>
          </ul>
          <nav v-if="totalPages > 1" class="mt-4 flex items-center justify-between text-sm">
            <button type="button" :disabled="page === 1" class="h-9 border border-line px-3 disabled:opacity-40" @click="page -= 1; loadPage()">{{ t('Previous') }}</button>
            <span class="tabular-nums text-muted">{{ page }} / {{ totalPages }}</span>
            <button type="button" :disabled="page === totalPages" class="h-9 border border-line px-3 disabled:opacity-40" @click="page += 1; loadPage()">{{ t('Next') }}</button>
          </nav>
        </section>

        <section aria-labelledby="segments-title" class="order-1 min-w-0 xl:order-2">
          <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="segments-title" class="text-base font-semibold">{{ t('Assembly segments') }}</h2>
              <p class="mt-1 text-sm text-muted">{{ t('Estimated length') }} {{ duration(estimatedSeconds) }}</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <template v-if="segmentSelectionMode">
                <button type="button" :disabled="selectedSegmentKeys.length === 0" class="h-9 border border-line px-3 text-sm text-danger disabled:opacity-40" @click="deleteSelectedSegments">{{ t('Delete') }}</button>
                <button type="button" :disabled="selectedSegmentKeys.length === 0" class="h-9 border border-line px-3 text-sm disabled:opacity-40" @click="copySelectedSegments">{{ t('Copy and add to end') }}</button>
              </template>
              <template v-else>
                <button type="button" class="h-9 border border-line px-3 text-sm" @click="addComment">{{ t('Add comment') }}</button>
                <button type="button" class="h-9 border border-line px-3 text-sm" @click="addSilence">{{ t('Add silence') }}</button>
                <button v-if="auth.isAdmin" type="button" class="h-9 border border-line px-3 text-sm" @click="addPlaceholder">{{ t('Add placeholder') }}</button>
                <button v-if="auth.isAdmin" type="button" class="h-9 border border-line px-3 text-sm" @click="addSmart">{{ t('Add smart segment') }}</button>
              </template>
              <button type="button" :disabled="!segmentSelectionMode && segments.length === 0" class="h-9 border border-line px-3 text-sm disabled:opacity-40" @click="toggleSegmentSelectionMode">{{ t(segmentSelectionMode ? 'Cancel' : 'Select') }}</button>
            </div>
          </div>

          <div v-if="previewBusy || previewMediaUrl" class="mb-4 border-y border-line py-3">
            <div class="flex items-center justify-between gap-3 text-sm">
              <span>{{ t('Assembly playback preview') }}</span>
              <div v-if="previewBusy" class="flex items-center gap-3">
                <span class="text-muted">{{ t('Preparing playback') }} {{ previewJob?.progress ?? 0 }}%</span>
                <button type="button" class="text-danger" @click="cancelPendingPreview()">{{ t('Cancel preview') }}</button>
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
          <ol
            v-else
            ref="segmentList"
            class="divide-y divide-line overflow-y-auto overscroll-contain border-y border-line"
            :class="previewMediaUrl ? 'max-h-[70vh]' : 'max-h-[85vh]'"
          >
            <li v-for="(segment, index) in segments" :key="segment.key" class="grid min-w-0 gap-4 py-4 sm:grid-cols-[2rem_minmax(0,1fr)_auto]">
              <div class="flex flex-col items-center gap-2 pt-1">
                <span class="text-sm tabular-nums text-muted">{{ index + 1 }}</span>
                <input
                  v-if="segmentSelectionMode"
                  type="checkbox"
                  class="h-4 w-4"
                  :checked="selectedSegmentKeys.includes(segment.key)"
                  :aria-label="t('Select segment {position}', { position: index + 1 })"
                  @change="setSegmentSelected(segment.key, ($event.target as HTMLInputElement).checked)"
                />
              </div>
              <div class="min-w-0">
                <template v-if="segment.type === 'silence'">
                  <p class="text-sm font-semibold">{{ t('Silence') }}</p>
                  <label class="mt-3 block text-xs text-muted">{{ t('Duration seconds') }}
                    <input :value="seconds(segment.silenceMilliseconds)" type="number" min="0" max="60" step="0.1" class="mt-1 h-9 w-36 border border-line px-2 text-sm text-ink" @input="segment.silenceMilliseconds = millisecondsFromInput($event)" />
                  </label>
                </template>
                <template v-else-if="segment.type === 'comment'">
                  <p class="text-sm font-semibold">{{ t('Comment') }}</p>
                  <template v-if="segment.commentEditing">
                    <label class="mt-3 block text-xs text-muted">{{ t('Comment text') }}
                      <textarea v-model="segment.commentText" rows="4" class="mt-1 w-full resize-y border border-line px-3 py-2 text-sm leading-6 text-ink" />
                    </label>
                  </template>
                  <template v-else>
                    <p class="mt-3 whitespace-pre-wrap break-words text-sm leading-6">{{ segment.commentText }}</p>
                  </template>
                  <div class="mt-3 flex items-center gap-5">
                    <button v-if="segment.commentEditing" type="button" :disabled="!segment.commentText?.trim()" class="h-9 bg-ink px-3 text-sm font-medium text-white disabled:opacity-40" @click="confirmComment(segment)">{{ t('Confirm') }}</button>
                    <button v-else type="button" class="h-9 border border-line px-3 text-sm font-medium" @click="segment.commentEditing = true">{{ t('Edit') }}</button>
                    <label class="inline-flex items-center gap-2 text-sm"><input v-model="segment.includeText" type="checkbox" />{{ t('Include text') }}</label>
                  </div>
                </template>
                <template v-else-if="segment.type === 'smart'">
                  <p class="text-sm font-semibold">{{ t(isQuestionCountSilence(segment) ? 'Question-count smart silence' : 'Smart question-number audio') }}</p>
                  <label class="mt-3 block text-xs text-muted">{{ t('Smart segment mode') }}
                    <select :value="segment.smartMode" class="mt-1 h-9 w-full border border-line bg-surface px-2 text-sm text-ink" @change="setSmartMode(segment, ($event.target as HTMLSelectElement).value as AssemblySmartMode)">
                      <option value="question_number">{{ t('Question-number audio') }}</option>
                      <option value="question_count_silence">{{ t('Question-count silence') }}</option>
                    </select>
                  </label>
                  <template v-if="isQuestionCountSilence(segment)">
                    <label class="mt-3 block text-xs text-muted">{{ t('Associated placeholder') }}
                      <select :value="smartSilenceAssociation(segment)" class="mt-1 h-9 w-full border border-line bg-surface px-2 text-sm text-ink" @change="setSmartSilenceAssociation(segment, ($event.target as HTMLSelectElement).value as SmartSilenceAssociation)">
                        <option value="">{{ t('Select a placeholder') }}</option>
                        <option value="previous">{{ t('Previous placeholder') }}</option>
                        <option value="next">{{ t('Next placeholder') }}</option>
                      </select>
                    </label>
                    <label class="mt-3 block text-xs text-muted">{{ t('Seconds per question') }}
                      <input :value="seconds(segment.silenceMilliseconds)" type="number" min="0" max="60" step="0.1" class="mt-1 h-9 w-36 border border-line px-2 text-sm text-ink" @input="segment.silenceMilliseconds = millisecondsFromInput($event)" />
                    </label>
                  </template>
                  <template v-else>
                    <p class="mt-2 text-xs text-muted">{{ t('Resolved when the paper is submitted') }}</p>
                    <div class="mt-3 flex flex-wrap gap-5 text-sm">
                      <label class="inline-flex items-center gap-2"><input v-model="segment.includeText" type="checkbox" />{{ t('Include text') }}</label>
                      <label class="inline-flex items-center gap-2"><input :checked="segment.includeTopic" type="checkbox" @change="setSegmentTopic(segment, ($event.target as HTMLInputElement).checked)" />{{ t('Include topic') }}</label>
                    </div>
                  </template>
                </template>
                <template v-else>
                  <div class="flex flex-wrap items-baseline gap-2">
                    <p class="break-words text-sm font-semibold">{{ segment.audio?.title || t('Unfilled placeholder') }}</p>
                    <span v-if="segment.type === 'placeholder'" class="text-xs text-accent">{{ t('Placeholder') }}</span>
                  </div>
                  <label v-if="segment.type === 'placeholder' && !segment.audio" class="mt-3 block text-xs text-muted">{{ t('Suggested search') }}
                    <input v-model="segment.suggestedQuery" maxlength="1024" class="mt-1 h-9 w-full border border-line px-2 text-sm text-ink" />
                  </label>
                  <div v-if="segment.type === 'placeholder'" class="mt-3 flex flex-wrap items-center gap-4">
                    <button type="button" class="text-sm font-medium text-accent" @click="selectPlaceholder(index)">{{ t('Choose audio') }}</button>
                    <button v-if="segment.audioId" type="button" class="text-sm text-danger" @click="clearPlaceholderAudio(segment, index)">{{ t('Clear selected audio') }}</button>
                  </div>
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
                <div v-if="segment.type !== 'silence' && segment.type !== 'comment' && !isQuestionCountSilence(segment)" class="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    :disabled="previewBusy || !canPlaySegment(segment, index)"
                    class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm disabled:opacity-40"
                    @click="playPreview(index, false)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" /></svg>
                    {{ previewTargetMatches(pendingPreview, segment, index, false) && previewBusy ? t('Preparing playback') : previewTargetMatches(activePreview, segment, index, false) && previewPlaying ? t('Stop') : t('Play') }}
                  </button>
                  <button
                    type="button"
                    :disabled="previewBusy || !canPlaySegment(segment, index) || !isPreviewEndPositionValid(segment, index)"
                    class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm disabled:opacity-40"
                    @click="playPreview(index, true)"
                  >
                    <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 5v14M9 5l10 7-10 7V5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" /></svg>
                    {{ previewTargetMatches(pendingPreview, segment, index, true) && previewBusy ? t('Preparing playback') : previewTargetMatches(activePreview, segment, index, true) && previewPlaying ? t('Stop') : t('Play from here') }}
                  </button>
                  <label class="inline-flex h-9 items-center gap-2 text-sm text-muted">
                    {{ t('To') }}
                    <input
                      :value="segment.previewEndPosition ?? ''"
                      :aria-label="t('Preview end segment')"
                      type="number"
                      :min="index + 1"
                      :max="segments.length"
                      step="1"
                      class="h-9 w-16 border border-line px-2 text-sm text-ink"
                      @input="setPreviewEndPosition(segment, $event)"
                    />
                    {{ t('segment') }}
                  </label>
                </div>
              </div>
              <div data-move-options class="relative flex justify-end gap-1">
                <button
                  type="button"
                  class="h-8 border border-line px-2 text-xs text-muted hover:border-ink hover:text-ink"
                  :aria-expanded="moveOptionsSegmentKey === segment.key"
                  @click="toggleMoveOptions(index)"
                >
                  {{ t('Move options') }}
                </button>
                <button type="button" :disabled="index === 0" class="flex h-8 w-7 items-center justify-center text-muted disabled:opacity-30" :title="t('Move up')" @click="move(index, -1)"><svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m6 15 6-6 6 6" stroke="currentColor" stroke-width="2" /></svg></button>
                <button type="button" :disabled="index === segments.length - 1" class="flex h-8 w-7 items-center justify-center text-muted disabled:opacity-30" :title="t('Move down')" @click="move(index, 1)"><svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" /></svg></button>
                <button type="button" class="flex h-8 w-7 items-center justify-center text-danger" :title="t('Remove')" @click="remove(index)"><svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 12h14" stroke="currentColor" stroke-width="2" /></svg></button>
                <div
                  v-if="moveOptionsSegmentKey === segment.key"
                  role="dialog"
                  :aria-label="t('Move options')"
                  class="absolute right-0 top-9 z-10 w-80 max-w-[calc(100vw-2rem)] border border-line bg-surface p-3 shadow-lg"
                >
                  <div class="flex flex-wrap items-center gap-2 text-sm">
                    <span>{{ t('Move direction') }}</span>
                    <select v-model="moveOptionsDirection" class="h-8 border border-line bg-surface px-2 text-sm text-ink">
                      <option value="up">{{ t('Up') }}</option>
                      <option value="down">{{ t('Down') }}</option>
                    </select>
                    <span>{{ t('Move count') }}</span>
                    <input v-model.number="moveOptionsDistance" :aria-label="t('Segment count')" type="number" min="1" step="1" class="h-8 w-16 border border-line px-2 text-sm text-ink" />
                    <span>{{ t('Segments') }}</span>
                    <button
                      type="button"
                      :aria-label="t('Move by offset')"
                      class="h-8 border border-line px-2 text-sm"
                      @click="moveByOptions(index)"
                    >
                      {{ t('Move') }}
                    </button>
                  </div>
                  <div class="mt-3 flex flex-wrap items-center gap-2 text-sm">
                    <span>{{ t('Move after') }}</span>
                    <input v-model.number="moveOptionsAfterPosition" :aria-label="t('Destination segment position')" type="number" min="0" :max="segments.length" step="1" class="h-8 w-16 border border-line px-2 text-sm text-ink" />
                    <span>{{ t('Segment suffix') }}</span>
                    <button
                      type="button"
                      :aria-label="t('Move after position')"
                      class="h-8 border border-line px-2 text-sm"
                      @click="moveAfterPosition(index)"
                    >
                      {{ t('Move') }}
                    </button>
                  </div>
                </div>
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

    <ConfirmDialog
      :open="pendingTemplateId !== null"
      :title="t('Replace existing segments?')"
      confirm-label="Replace"
      @close="closeTemplateReplacement"
      @confirm="confirmTemplateReplacement"
    >
      <p>{{ t('Selecting this template will replace the current segments.') }}</p>
    </ConfirmDialog>

    <ConfirmDialog
      :open="pendingTemplateOverwrite !== null"
      :title="t('Overwrite existing template?')"
      :busy="savingTemplate"
      confirm-label="Overwrite"
      @close="closeTemplateOverwrite"
      @confirm="confirmTemplateOverwrite"
    >
      <p>{{ t('A template titled {title} already exists. Overwrite it with the current segments?', { title: pendingTemplateOverwrite?.existingTitle ?? '' }) }}</p>
    </ConfirmDialog>
  </section>
</template>
