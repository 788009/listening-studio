import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createVoiceGenderTag,
  createVoiceUpload,
  deleteVoice,
  getVoice,
  listPublicSampleAudio,
  listVoiceGenderTags,
  listVoices,
  updateVoice,
  voiceSamplePath,
} from './voices'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('voice API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('builds typed list and detail requests', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ items: [], page: 1, pageSize: 100, total: 0 }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 7 }))
    vi.stubGlobal('fetch', fetchMock)

    await listVoices({ language: 'zh-CN', query: 'gender:female' })
    await getVoice(7, 'zh-CN')

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/voices?page=1&page_size=100&language=zh-CN&q=gender%3Afemale',
    )
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/voices/7?language=zh-CN')
  })

  it('updates, deletes, and resolves protected sample paths', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: 4 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await updateVoice(4, { sampleSource: 'original' })
    await deleteVoice(4)

    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ method: 'PATCH' }),
    )
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(voiceSamplePath(4)).toBe('/media/voice/4/sample')
    expect(() => voiceSamplePath(0)).toThrow('positive integer')
  })

  it('requests only public ready audio for sample selection', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [{ id: 2, title: 'Public sample' }],
        page: 1,
        pageSize: 100,
        total: 1,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(listPublicSampleAudio('en')).resolves.toHaveLength(1)
    expect(fetchMock.mock.calls[0]?.[0]).toContain('status=ready')
    expect(fetchMock.mock.calls[0]?.[0]).toContain('visibility=public')
  })

  it('submits voice creation as multipart data and loads gender tags', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ voiceId: 8, jobId: 13 }, 202))
      .mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['wav'], 'reference.wav', { type: 'audio/wav' })

    await expect(
      createVoiceUpload({
        title: 'Classroom voice',
        file,
        visibility: 'public',
        genderTagId: 4,
      }),
    ).resolves.toEqual({ voiceId: 8, jobId: 13 })
    await listVoiceGenderTags('zh-CN')

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(request.body).toBeInstanceOf(FormData)
    const form = request.body as FormData
    expect(form.get('title')).toBe('Classroom voice')
    expect(form.get('visibility')).toBe('public')
    expect(form.get('genderTagId')).toBe('4')
    expect(form.get('file')).toBe(file)
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      '/api/voice-tags?type=gender&language=zh-CN',
    )
  })

  it('creates a gender tag with a typed payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: 4, type: 'gender', englishValue: 'female' }, 201),
    )
    vi.stubGlobal('fetch', fetchMock)

    await createVoiceGenderTag('female', [
      { language: 'zh-CN', value: '女性' },
    ])

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/voice-tags')
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(JSON.parse(String(request.body))).toEqual({
      type: 'gender',
      value: 'female',
      translations: [{ language: 'zh-CN', value: '女性' }],
    })
  })
})
