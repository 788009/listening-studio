import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createGenerationBatch,
  getGenerationBatch,
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
      questionTypeCounts: { short_dialogue: 3, monologue: 1 },
      speakerVoiceMap: { Host: 7, Guest: 9 },
    })

    expect(JSON.parse(String(body?.get('questionTypeCounts')))).toEqual({
      short_dialogue: 3,
      monologue: 1,
    })
    expect(body?.getAll('tagIds')).toEqual([])
    expect(body?.get('corpus')).toBe('Corpus text')
    expect(JSON.parse(String(body?.get('speakerVoiceMap')))).toEqual({ Host: 7, Guest: 9 })
  })

  it('uses the owner-scoped detail endpoint', async () => {
    const calls: [string, RequestInit | undefined][] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        calls.push([String(input), init])
        return Promise.resolve(response({ id: 4 }))
      }),
    )

    await getGenerationBatch(4)

    expect(calls.map(([path]) => path)).toEqual(['/api/generation-batches/4'])
  })
})
