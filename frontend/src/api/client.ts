import { ApiError, isApiErrorEnvelope, type ApiErrorContent } from './errors'

const API_PREFIX = '/api'
const CSRF_COOKIE_NAME = 'listening_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'

function cookieValue(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${encodeURIComponent(name)}=`
  for (const part of document.cookie.split(';')) {
    const value = part.trim()
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length))
  }
  return null
}

function apiPath(path: string): string {
  if (/^[a-z][a-z\d+.-]*:/i.test(path) || path.startsWith('//')) {
    throw new TypeError('API paths must be relative')
  }
  return `${API_PREFIX}${path.startsWith('/') ? path : `/${path}`}`
}

function applicationPath(path: string): string {
  if (/^[a-z][a-z\d+.-]*:/i.test(path) || path.startsWith('//')) {
    throw new TypeError('Application paths must be relative')
  }
  return path.startsWith('/') ? path : `/${path}`
}

async function responseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    return null
  }
  try {
    return await response.json()
  } catch {
    return null
  }
}

export async function applicationRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  headers.set('Accept', 'application/json')
  const method = (init.method ?? 'GET').toUpperCase()
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const csrfToken = cookieValue(CSRF_COOKIE_NAME)
    if (csrfToken) headers.set(CSRF_HEADER_NAME, csrfToken)
  }

  const response = await fetch(applicationPath(path), {
    ...init,
    headers,
    credentials: 'include',
  })
  const body = await responseBody(response)
  const fallback: ApiErrorContent = {
    code: 'unexpected_response',
    message: 'The server returned an unexpected response',
    details: null,
    request_id: response.headers.get('X-Request-ID') ?? '',
  }

  if (!response.ok) {
    throw new ApiError(response.status, isApiErrorEnvelope(body) ? body.error : fallback)
  }

  if (response.status === 204) {
    return undefined as T
  }
  if (body === null) {
    throw new ApiError(response.status, fallback)
  }
  return body as T
}


export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  return applicationRequest<T>(apiPath(path), init)
}
