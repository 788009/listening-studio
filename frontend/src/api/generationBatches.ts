import { apiRequest } from './client'
import type { AudioQuestionInput } from './audios'

export type QuestionType = 'short_dialogue' | 'long_dialogue' | 'monologue'
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

export interface GenerationDraftUtterance {
  speakerDisplayName: string
  voiceId: number
  text: string
}

export interface GenerationDraft {
  questionType: QuestionType
  title: string
  utterances: GenerationDraftUtterance[]
  questions: AudioQuestionInput[]
}

export interface GenerationBatchItem {
  id: number
  position: number
  status: GenerationBatchStatus
  attemptCount: number
  draft?: GenerationDraft
  errorSummary?: string
}

export interface GenerationBatchSpeakerVoice {
  speaker: string
  voiceId: number
}

export interface GenerationBatch {
  id: number
  jobId: number
  questionTypeCounts: Partial<Record<QuestionType, number>>
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

export interface GenerationBatchCreationInput {
  corpus?: string
  file?: File
  encoding?: string
  questionType: QuestionType
  count: number
  speakerVoiceMap: Record<string, number>
}

export function createGenerationBatch(
  input: GenerationBatchCreationInput,
): Promise<GenerationBatchAccepted> {
  const form = new FormData()
  form.set('questionType', input.questionType)
  form.set('count', String(input.count))
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

export function reviseGenerationDraft(
  batchId: number,
  prompt: string,
  draft: GenerationDraft,
): Promise<GenerationDraft> {
  return apiRequest<GenerationDraft>(
    `/generation-batches/${positiveId(batchId)}/revise-draft`,
    {
      method: 'POST',
      body: JSON.stringify({ prompt, draft }),
    },
  )
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
