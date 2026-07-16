import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createGenerationBatch,
  getGenerationBatch,
  retryGenerationBatchItem,
  updateCompletedBatchAudios,
} from './generationBatches'


function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('generation batch API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('submits repeated fields and a speaker voice map as multipart data', async () => {
    let body: FormData | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        body = init?.body as FormData
        return Promise.resolve(response({ batchId: 4, jobId: 8 }))
      }),
    )

    await createGenerationBatch({
      corpus: 'Corpus text',
      questionTypes: ['multiple_choice', 'short_answer'],
      count: 2,
      tagIds: [3, 5],
      speakerVoiceMap: { Host: 7, Guest: 9 },
    })

    expect(body?.getAll('questionTypes')).toEqual(['multiple_choice', 'short_answer'])
    expect(body?.getAll('tagIds')).toEqual(['3', '5'])
    expect(body?.get('corpus')).toBe('Corpus text')
    expect(JSON.parse(String(body?.get('speakerVoiceMap')))).toEqual({ Host: 7, Guest: 9 })
  })

  it('uses owner-scoped detail, retry, and bulk update endpoints', async () => {
    const calls: [string, RequestInit | undefined][] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        calls.push([String(input), init])
        return Promise.resolve(response({ updatedCount: 2 }))
      }),
    )

    await getGenerationBatch(4)
    await retryGenerationBatchItem(4, 6)
    await updateCompletedBatchAudios(4, [3], 'public')

    expect(calls.map(([path]) => path)).toEqual([
      '/api/generation-batches/4',
      '/api/generation-batches/4/items/6/retry',
      '/api/generation-batches/4/completed-audios',
    ])
    expect(calls[2]?.[1]?.method).toBe('PATCH')
  })
})
