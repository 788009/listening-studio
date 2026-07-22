import { apiRequest } from './client'
import type { ResourceVisibility } from './audios'

export type AssemblySegmentType = 'audio' | 'silence' | 'placeholder' | 'smart'

export interface AssemblySegmentInput {
  type: AssemblySegmentType
  audioId?: number
  suggestedQuery?: string
  silenceMilliseconds?: number
  repeatCount?: number
  repeatIntervalMilliseconds?: number
  includeText?: boolean
  includeTopic?: boolean
}

export interface AssemblyTemplateSegment extends AssemblySegmentInput {
  id: number
  position: number
}

export interface AssemblyTemplate {
  id: number
  title: string
  ownerUserId: string
  segments: AssemblyTemplateSegment[]
  createdAt: string
  updatedAt: string
}

export interface AssemblyCreateInput {
  title: string
  templateId?: number
  segments: AssemblySegmentInput[]
  tagIds: number[]
  visibility: ResourceVisibility
}

export interface AssemblyAccepted {
  audioId: number
  jobId: number
}

export function listAssemblyTemplates(): Promise<AssemblyTemplate[]> {
  return apiRequest<AssemblyTemplate[]>('/assembly-templates')
}

export function createAssemblyTemplate(input: {
  title: string
  segments: AssemblySegmentInput[]
}): Promise<AssemblyTemplate> {
  return apiRequest<AssemblyTemplate>('/assembly-templates', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function deleteAssemblyTemplate(templateId: number): Promise<void> {
  return apiRequest<void>(`/assembly-templates/${positiveId(templateId)}`, {
    method: 'DELETE',
  })
}

export function createAssembly(input: AssemblyCreateInput): Promise<AssemblyAccepted> {
  return apiRequest<AssemblyAccepted>('/assemblies', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
