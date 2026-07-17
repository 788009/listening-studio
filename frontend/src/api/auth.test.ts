import { afterEach, describe, expect, it, vi } from 'vitest'

import { createDebugSession, endSession, getAuthenticationCapabilities } from './auth'


describe('authentication API', () => {
  afterEach(() => {
    document.cookie = 'listening_csrf=; Max-Age=0; Path=/'
    vi.unstubAllGlobals()
  })

  it('discovers login capabilities on the auth prefix', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ loginMethod: 'debug', loginUrl: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(getAuthenticationCapabilities()).resolves.toEqual({
      loginMethod: 'debug',
      loginUrl: null,
    })
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/auth/capabilities')
  })

  it('creates a debug session from structured identity values', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await createDebugSession({ issuer: 'https://local.test', subject: 'teacher-1' })

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/auth/debug/session')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      issuer: 'https://local.test',
      subject: 'teacher-1',
    })
  })

  it('sends CSRF on logout and returns the provider redirect', async () => {
    document.cookie = 'listening_csrf=csrf-token; Path=/'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ redirectUrl: 'https://issuer.test/logout' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(endSession()).resolves.toEqual({
      redirectUrl: 'https://issuer.test/logout',
    })
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-token')
  })
})
