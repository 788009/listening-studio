import { afterEach, describe, expect, it, vi } from 'vitest'

import { cancelJob, getJob } from './jobs'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('job API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('gets and cancels an owned job', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: 13, status: 'queued' }))
      .mockResolvedValueOnce(jsonResponse({ id: 13, status: 'cancelled' }))
    vi.stubGlobal('fetch', fetchMock)

    await getJob(13)
    await cancelJob(13)

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/jobs/13')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/jobs/13/cancel')
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ method: 'POST' }),
    )
    expect(() => getJob(0)).toThrow('positive integer')
  })
})
