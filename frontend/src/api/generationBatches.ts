import { apiRequest } from './client'
import type { ResourceVisibility } from './voices'

export type QuestionType =
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_blank'
  | 'short_answer'
export type GenerationBatchStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface GenerationBatchTag {
  id: number
  type: 'topic' | 'category'
  englishValue: string
}

export interface GenerationBatchItem {
  id: number
  position: number
  status: GenerationBatchStatus
  audioId?: number
  errorSummary?: string
  questionTypes?: QuestionType[]
  attemptCount: number
  title?: string
}

export interface GenerationBatchSpeakerVoice {
  speaker: string
  voiceId: number
}

export interface GenerationBatch {
  id: number
  jobId: number
  questionTypes: QuestionType[]
  requestedCount: number
  status: GenerationBatchStatus
  progress: number
  tags: GenerationBatchTag[]
  items: GenerationBatchItem[]
  speakerVoices: GenerationBatchSpeakerVoice[]
  errorSummary?: string
  createdAt: string
  updatedAt: string
}

export interface GenerationBatchAccepted {
  batchId: number
  jobId: number
}

export interface GenerationBatchRetryAccepted extends GenerationBatchAccepted {
  itemId: number
}

export interface GenerationBatchCreationInput {
  corpus?: string
  file?: File
  encoding?: string
  questionTypes: QuestionType[]
  count: number
  tagIds: number[]
  speakerVoiceMap: Record<string, number>
}

export function createGenerationBatch(
  input: GenerationBatchCreationInput,
): Promise<GenerationBatchAccepted> {
  const form = new FormData()
  for (const questionType of input.questionTypes) {
    form.append('questionTypes', questionType)
  }
  form.set('count', String(input.count))
  for (const tagId of input.tagIds) form.append('tagIds', String(tagId))
  form.set('speakerVoiceMap', JSON.stringify(input.speakerVoiceMap))
  if (input.file) {
    form.set('file', input.file)
    form.set('encoding', input.encoding ?? 'utf-8')
  } else {
    form.set('corpus', input.corpus ?? '')
  }
  return apiRequest<GenerationBatchAccepted>('/generation-batches', {
    method: 'POST',
    body: form,
  })
}

export function getGenerationBatch(batchId: number): Promise<GenerationBatch> {
  return apiRequest<GenerationBatch>(`/generation-batches/${positiveId(batchId)}`)
}

export function retryGenerationBatchItem(
  batchId: number,
  itemId: number,
): Promise<GenerationBatchRetryAccepted> {
  return apiRequest<GenerationBatchRetryAccepted>(
    `/generation-batches/${positiveId(batchId)}/items/${positiveId(itemId)}/retry`,
    { method: 'POST' },
  )
}

export function updateCompletedBatchAudios(
  batchId: number,
  tagIds: number[],
  visibility: ResourceVisibility,
): Promise<{ updatedCount: number }> {
  return apiRequest<{ updatedCount: number }>(
    `/generation-batches/${positiveId(batchId)}/completed-audios`,
    {
      method: 'PATCH',
      body: JSON.stringify({ tagIds, visibility }),
    },
  )
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
