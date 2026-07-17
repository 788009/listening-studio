import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiRequest, applicationRequest } from './client'
import { ApiError } from './errors'


describe('apiRequest', () => {
  afterEach(() => {
    document.cookie = 'listening_csrf=; Max-Age=0; Path=/'
    vi.unstubAllGlobals()
  })

  it('uses the relative API prefix and includes credentials', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest<{ id: number }>('/voices')).resolves.toEqual({ id: 1 })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/voices',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('maps the server error envelope to ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'not_found',
              message: 'Resource not found',
              details: null,
              request_id: 'request-123',
            },
          }),
          { status: 404, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const request = apiRequest('/voices/1')
    await expect(request).rejects.toBeInstanceOf(ApiError)
    await expect(request).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
      requestId: 'request-123',
    })
  })

  it('rejects absolute request URLs', async () => {
    await expect(apiRequest('https://example.com/api')).rejects.toThrow(
      'API paths must be relative',
    )
  })

  it('supports non-API application routes without allowing absolute URLs', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await applicationRequest('/auth/session', { method: 'DELETE' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/session',
      expect.objectContaining({ method: 'DELETE', credentials: 'include' }),
    )
    await expect(applicationRequest('https://example.com/auth')).rejects.toThrow(
      'Application paths must be relative',
    )
  })

  it('adds the CSRF cookie value to write requests', async () => {
    document.cookie = 'listening_csrf=csrf-token; Path=/'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await apiRequest('/users/me/profile', {
      method: 'PATCH',
      body: JSON.stringify({ username: 'Teacher' }),
    })

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-token')
  })
})
