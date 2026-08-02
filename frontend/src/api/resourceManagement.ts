import { apiRequest } from './client'
import type { ResourceVisibility, VoiceAuthor } from './voices'

export type ManagedResourceKind =
  | 'voice'
  | 'audio'
  | 'generation_batch'
  | 'paper'
export type BulkOutcome = 'success' | 'conflict' | 'failed'

export interface ManagedTag {
  id: number
  type: string
  value: string
}

export interface ManagedReference {
  type: string
  count: number
}

export interface ManagedResource {
  id: number
  kind: ManagedResourceKind
  author: VoiceAuthor
  title: string
  status: string
  visibility?: ResourceVisibility
  tags: ManagedTag[]
  createdAt: string
  references: ManagedReference[]
  canDelete: boolean
}

export interface ManagedResourceList {
  items: ManagedResource[]
  page: number
  pageSize: number
  total: number
}

export interface ManagedResourceListOptions {
  kind: ManagedResourceKind
  page?: number
  pageSize?: number
  status?: string
  visibility?: ResourceVisibility
  tagIds?: number[]
  createdFrom?: string
  createdBefore?: string
  query?: string
}

export interface BulkResourceUpdateInput {
  kind: 'voice' | 'audio'
  resourceIds: number[]
  visibility?: ResourceVisibility
  tagIds?: number[]
}

export interface BulkItemResult {
  id: number
  outcome: BulkOutcome
  message: string
}

export interface BulkResourceUpdateResult {
  items: BulkItemResult[]
  successCount: number
  conflictCount: number
  failedCount: number
}

export function listManagedResources(
  options: ManagedResourceListOptions,
): Promise<ManagedResourceList> {
  const parameters = new URLSearchParams({
    kind: options.kind,
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 20),
  })
  if (options.status) parameters.set('status', options.status)
  if (options.visibility) parameters.set('visibility', options.visibility)
  for (const tagId of options.tagIds ?? []) {
    parameters.append('tagId', String(positiveId(tagId)))
  }
  if (options.createdFrom) parameters.set('created_from', options.createdFrom)
  if (options.createdBefore) parameters.set('created_before', options.createdBefore)
  if (options.query?.trim()) parameters.set('q', options.query.trim())
  return apiRequest<ManagedResourceList>(
    `/resource-management?${parameters.toString()}`,
  )
}

export function bulkUpdateManagedResources(
  input: BulkResourceUpdateInput,
): Promise<BulkResourceUpdateResult> {
  return apiRequest<BulkResourceUpdateResult>('/resource-management/bulk-update', {
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
