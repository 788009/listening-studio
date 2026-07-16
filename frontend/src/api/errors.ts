import { translateApiError } from '@/i18n'

export interface ApiErrorContent {
  code: string
  message: string
  details: unknown
  request_id: string
}

export interface ApiErrorEnvelope {
  error: ApiErrorContent
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(status: number, content: ApiErrorContent) {
    super(translateApiError(content.code, content.message))
    this.name = 'ApiError'
    this.status = status
    this.code = content.code
    this.details = content.details
    this.requestId = content.request_id || null
  }
}

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) {
    return false
  }
  const error = value.error
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof error.code === 'string' &&
    'message' in error &&
    typeof error.message === 'string' &&
    'request_id' in error &&
    typeof error.request_id === 'string'
  )
}
