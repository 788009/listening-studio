import { apiRequest } from './client'

export type ResourceStatus = 'pending' | 'processing' | 'ready' | 'failed'
export type ResourceVisibility = 'private' | 'public'
export type VoiceSampleSource = 'original' | 'public_audio'
export type VoiceTagType = 'author' | 'gender'

export interface TagTranslation {
  language: string
  value: string
}

export interface VoiceTag {
  id: number
  type: VoiceTagType
  englishValue: string
  displayValue: string
  fullTag: string
  translations: TagTranslation[]
}

export interface VoiceAuthor {
  userId: string
  username: string | null
}

export interface Voice {
  id: number
  author: VoiceAuthor
  title: string
  status: ResourceStatus
  visibility: ResourceVisibility
  sampleSource: VoiceSampleSource
  sampleAudioId?: number
  errorSummary?: string
  tags: VoiceTag[]
}

export interface VoiceList {
  items: Voice[]
  page: number
  pageSize: number
  total: number
}

export interface VoiceUpdate {
  title?: string
  visibility?: ResourceVisibility
  genderTagIds?: number[]
  sampleSource?: VoiceSampleSource
  sampleAudioId?: number | null
}

export interface VoiceUploadAccepted {
  voiceId: number
  jobId: number
}

export interface VoiceUploadInput {
  title: string
  file: File
  visibility: ResourceVisibility
  genderTagId?: number
}

export interface AudioSummary {
  id: number
  title: string
  author: VoiceAuthor
  status: ResourceStatus
  visibility: ResourceVisibility
}

interface AudioList {
  items: AudioSummary[]
  page: number
  pageSize: number
  total: number
}

export interface VoiceListOptions {
  language?: string
  page?: number
  pageSize?: number
  query?: string
}

export function listVoices(options: VoiceListOptions = {}): Promise<VoiceList> {
  const parameters = new URLSearchParams()
  parameters.set('page', String(options.page ?? 1))
  parameters.set('page_size', String(options.pageSize ?? 100))
  parameters.set('language', options.language ?? 'en')
  if (options.query?.trim()) {
    parameters.set('q', options.query.trim())
  }
  return apiRequest<VoiceList>(`/voices?${parameters.toString()}`)
}

export function getVoice(voiceId: number, language = 'en'): Promise<Voice> {
  return apiRequest<Voice>(
    `/voices/${positiveId(voiceId)}?language=${encodeURIComponent(language)}`,
  )
}

export function updateVoice(voiceId: number, update: VoiceUpdate): Promise<Voice> {
  return apiRequest<Voice>(`/voices/${positiveId(voiceId)}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

export function deleteVoice(voiceId: number): Promise<void> {
  return apiRequest<void>(`/voices/${positiveId(voiceId)}`, { method: 'DELETE' })
}

export function createVoiceUpload(
  input: VoiceUploadInput,
): Promise<VoiceUploadAccepted> {
  const form = new FormData()
  form.set('title', input.title)
  form.set('file', input.file)
  form.set('visibility', input.visibility)
  if (input.genderTagId !== undefined) {
    form.set('genderTagId', String(input.genderTagId))
  }
  return apiRequest<VoiceUploadAccepted>('/voices', {
    method: 'POST',
    body: form,
  })
}

export function listVoiceGenderTags(language = 'en'): Promise<VoiceTag[]> {
  const parameters = new URLSearchParams({ type: 'gender', language })
  return apiRequest<VoiceTag[]>(`/voice-tags?${parameters.toString()}`)
}

export function listPublicSampleAudio(language = 'en'): Promise<AudioSummary[]> {
  const parameters = new URLSearchParams({
    page: '1',
    page_size: '100',
    language,
    status: 'ready',
    visibility: 'public',
  })
  return apiRequest<AudioList>(`/audios?${parameters.toString()}`).then(
    (response) => response.items,
  )
}

export function voiceSamplePath(voiceId: number): string {
  return `/media/voice/${positiveId(voiceId)}/sample`
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
