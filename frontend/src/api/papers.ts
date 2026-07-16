import { apiRequest } from './client'

export type PaperStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface PaperPreset {
  id: number
  name: string
  isBuiltin: boolean
  introSilenceMilliseconds: number
  interItemSilenceMilliseconds: number
  repeatCount: number
  outroSilenceMilliseconds: number
}

export interface PaperItem {
  id: number
  audioId: number
  title: string
  position: number
}

export interface Paper {
  id: number
  title: string
  status: PaperStatus
  presetId?: number
  presetName?: string
  introSilenceMilliseconds: number
  interItemSilenceMilliseconds: number
  repeatCount: number
  outroSilenceMilliseconds: number
  resultAudioId?: number
  errorSummary?: string
  items: PaperItem[]
  createdAt: string
  updatedAt: string
}

export interface PaperCreateInput {
  title: string
  presetId: number
  audioIds: number[]
}

export interface PaperRenderAccepted {
  paperId: number
  audioId: number
  jobId: number
}

export function listPaperPresets(): Promise<PaperPreset[]> {
  return apiRequest<PaperPreset[]>('/paper-presets')
}

export function createPaper(input: PaperCreateInput): Promise<Paper> {
  return apiRequest<Paper>('/papers', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function renderPaper(paperId: number): Promise<PaperRenderAccepted> {
  return apiRequest<PaperRenderAccepted>(`/papers/${positiveId(paperId)}/render`, {
    method: 'POST',
  })
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
