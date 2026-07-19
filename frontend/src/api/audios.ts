import { apiRequest } from './client'
import type {
  ResourceStatus,
  ResourceVisibility,
  TagTranslation,
  VoiceAuthor,
} from './voices'

export type { ResourceStatus, ResourceVisibility } from './voices'

export type AudioSourceType =
  | 'single_speaker'
  | 'multi_turn'
  | 'corpus'
  | 'assembly'
export type AudioTagType = 'author' | 'speaker' | 'topic' | 'category'

export interface AudioTag {
  id: number
  type: AudioTagType
  englishValue: string
  displayValue: string
  fullTag: string
  translations: TagTranslation[]
}

export interface AudioTagCreationInput {
  type: Extract<AudioTagType, 'topic' | 'category'>
  englishValue: string
  translations: TagTranslation[]
}

export interface AudioUtterance {
  voiceId?: number | null
  voiceTitle?: string | null
  speakerTag?: string | null
  speakerDisplayName: string
  text: string
  position: number
}

export interface Audio {
  id: number
  author: VoiceAuthor
  title: string
  text: string
  sourceType: AudioSourceType
  status: ResourceStatus
  visibility: ResourceVisibility
  durationSeconds: number | null
  sampleRate: number | null
  errorSummary?: string
  tags: AudioTag[]
  utterances: AudioUtterance[]
}

export interface AudioList {
  items: Audio[]
  page: number
  pageSize: number
  total: number
}

export interface AudioListOptions {
  language?: string
  page?: number
  pageSize?: number
  query?: string
  status?: ResourceStatus
  visibility?: ResourceVisibility
}

export interface AudioUpdate {
  title?: string
  visibility?: ResourceVisibility
  tagIds?: number[]
}

export interface AudioCreationAccepted {
  audioId: number
  jobId: number
}

export interface SingleAudioCreationInput {
  title: string
  text: string
  voiceId: number
  speakerDisplayName: string
  tagIds: number[]
  visibility: ResourceVisibility
}

export interface DialogueCreationUtterance {
  voiceId: number
  speakerDisplayName: string
  text: string
}

export interface DialogueAudioCreationInput {
  title: string
  utterances: DialogueCreationUtterance[]
  tagIds: number[]
  visibility: ResourceVisibility
}

export function listAudios(options: AudioListOptions = {}): Promise<AudioList> {
  const parameters = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 20),
    language: options.language ?? 'en',
  })
  if (options.query?.trim()) parameters.set('q', options.query.trim())
  if (options.status) parameters.set('status', options.status)
  if (options.visibility) parameters.set('visibility', options.visibility)
  return apiRequest<AudioList>(`/audios?${parameters.toString()}`)
}

export function getAudio(audioId: number, language = 'en'): Promise<Audio> {
  return apiRequest<Audio>(
    `/audios/${positiveId(audioId)}?language=${encodeURIComponent(language)}`,
  )
}

export function updateAudio(audioId: number, update: AudioUpdate): Promise<Audio> {
  return apiRequest<Audio>(`/audios/${positiveId(audioId)}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

export function deleteAudio(audioId: number): Promise<void> {
  return apiRequest<void>(`/audios/${positiveId(audioId)}`, { method: 'DELETE' })
}

export function createSingleAudio(
  input: SingleAudioCreationInput,
): Promise<AudioCreationAccepted> {
  return apiRequest<AudioCreationAccepted>('/audios', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createDialogueAudio(
  input: DialogueAudioCreationInput,
): Promise<AudioCreationAccepted> {
  return apiRequest<AudioCreationAccepted>('/audios/dialogues', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function audioMediaPath(audioId: number): string {
  return `/media/audio/${positiveId(audioId)}`
}

export function listAudioTags(language = 'en'): Promise<AudioTag[]> {
  return apiRequest<AudioTag[]>(
    `/audio-tags?language=${encodeURIComponent(language)}`,
  )
}

export async function listAudioCreationTags(language = 'en'): Promise<AudioTag[]> {
  const encodedLanguage = encodeURIComponent(language)
  const [topics, categories] = await Promise.all([
    apiRequest<AudioTag[]>(`/audio-tags?type=topic&language=${encodedLanguage}`),
    apiRequest<AudioTag[]>(`/audio-tags?type=category&language=${encodedLanguage}`),
  ])
  return [...topics, ...categories]
}

export function createAudioTag(input: AudioTagCreationInput): Promise<AudioTag> {
  return apiRequest<AudioTag>('/audio-tags', {
    method: 'POST',
    body: JSON.stringify({
      type: input.type,
      value: input.englishValue,
      translations: input.translations,
    }),
  })
}

export function autocompleteAudioTags(query: string): Promise<string[]> {
  const parameters = new URLSearchParams({ q: query, limit: '10' })
  return apiRequest<string[]>(`/audio-tags/autocomplete?${parameters.toString()}`)
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
