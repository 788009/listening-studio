import { apiRequest } from './client'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface JobResult {
  type: string
  id: number
}

export interface Job {
  id: number
  type: string
  status: JobStatus
  progress: number
  inputSummary: Record<string, unknown>
  result?: JobResult
  errorSummary?: string
  cancelRequested: boolean
  retryable: boolean
  attemptCount: number
  createdAt: string
  updatedAt: string
  startedAt?: string
  finishedAt?: string
}

export function getJob(jobId: number): Promise<Job> {
  return apiRequest<Job>(`/jobs/${positiveId(jobId)}`)
}

export function cancelJob(jobId: number): Promise<Job> {
  return apiRequest<Job>(`/jobs/${positiveId(jobId)}/cancel`, { method: 'POST' })
}

function positiveId(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError('Resource ID must be a positive integer')
  }
  return value
}
