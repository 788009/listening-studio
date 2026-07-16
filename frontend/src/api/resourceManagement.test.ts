import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  bulkUpdateManagedResources,
  listManagedResources,
} from './resourceManagement'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('resource management API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('serializes server filters and detailed bulk updates', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ items: [], page: 2, pageSize: 20, total: 0 }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [{ id: 3, outcome: 'success', message: 'Updated' }],
          successCount: 1,
          conflictCount: 0,
          failedCount: 0,
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await listManagedResources({
      kind: 'audio',
      page: 2,
      visibility: 'private',
      status: 'ready',
      tagIds: [4, 5],
      createdFrom: '2026-01-01T00:00:00.000Z',
      query: 'lesson',
    })
    await bulkUpdateManagedResources({
      kind: 'audio',
      resourceIds: [3],
      visibility: 'public',
      tagIds: [4],
    })

    const listPath = String(fetchMock.mock.calls[0]?.[0])
    expect(listPath).toContain('kind=audio')
    expect(listPath).toContain('page=2')
    expect(listPath).toContain('tagId=4&tagId=5')
    expect(listPath).toContain('q=lesson')
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      kind: 'audio',
      resourceIds: [3],
      visibility: 'public',
      tagIds: [4],
    })
  })
})
