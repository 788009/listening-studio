import { afterEach, describe, expect, it, vi } from 'vitest'

import { createPaper, listPaperPresets, renderPaper } from './papers'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('paper API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads presets, creates an ordered paper, and starts rendering', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([{ id: 1, name: 'Standard' }]))
      .mockResolvedValueOnce(jsonResponse({ id: 7 }, 201))
      .mockResolvedValueOnce(
        jsonResponse({ paperId: 7, audioId: 9, jobId: 11 }, 202),
      )
    vi.stubGlobal('fetch', fetchMock)

    await listPaperPresets()
    await createPaper({ title: 'Midterm', presetId: 2, audioIds: [5, 3] })
    await renderPaper(7)

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/paper-presets')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/papers')
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      title: 'Midterm',
      presetId: 2,
      audioIds: [5, 3],
    })
    expect(fetchMock.mock.calls[2]?.[0]).toBe('/api/papers/7/render')
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(
      expect.objectContaining({ method: 'POST' }),
    )
    expect(() => renderPaper(0)).toThrow('positive integer')
  })
})
