import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  audioMediaPath,
  autocompleteAudioTags,
  deleteAudio,
  getAudio,
  listAudios,
  updateAudio,
} from './audios'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('audio API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('builds public search and localized detail requests', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ items: [], page: 2, pageSize: 20, total: 0 }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 5 }))
    vi.stubGlobal('fetch', fetchMock)

    await listAudios({
      language: 'zh-CN',
      page: 2,
      query: 'topic:climate_change',
      status: 'ready',
      visibility: 'public',
    })
    await getAudio(5, 'zh-CN')

    expect(fetchMock.mock.calls[0]?.[0]).toContain('q=topic%3Aclimate_change')
    expect(fetchMock.mock.calls[0]?.[0]).toContain('visibility=public')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/audios/5?language=zh-CN')
  })

  it('updates and deletes owner audio', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: 5 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await updateAudio(5, { title: 'Updated', visibility: 'private' })
    await deleteAudio(5)

    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ method: 'PATCH' }),
    )
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(audioMediaPath(5)).toBe('/media/audio/5')
  })

  it('uses the English full tag autocomplete endpoint value', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(['topic:climate_change']))
    vi.stubGlobal('fetch', fetchMock)

    await expect(autocompleteAudioTags('气候')).resolves.toEqual([
      'topic:climate_change',
    ])
    expect(fetchMock.mock.calls[0]?.[0]).toContain('%E6%B0%94%E5%80%99')
  })
})
