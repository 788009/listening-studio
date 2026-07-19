import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createSingleAudio } from '@/api/audios'
import { getJob } from '@/api/jobs'
import { useAudioCreationStore } from './audioCreation'

vi.mock('@/api/audios', () => ({
  createDialogueAudio: vi.fn(),
  createSingleAudio: vi.fn(),
}))
vi.mock('@/api/jobs', () => ({ getJob: vi.fn() }))

const input = {
  title: 'Practice',
  text: 'Listening text',
  voiceId: 2,
  speakerDisplayName: 'Woman',
  tagIds: [],
  visibility: 'private' as const,
}

describe('audio creation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('prevents a duplicate submit and persists the active task', async () => {
    let accept: ((value: { audioId: number; jobId: number }) => void) | undefined
    vi.mocked(createSingleAudio).mockReturnValue(
      new Promise((resolve) => {
        accept = resolve
      }),
    )
    vi.mocked(getJob).mockResolvedValue({
      id: 13,
      type: 'audio_synthesis',
      status: 'queued',
      progress: 0,
      inputSummary: {},
      cancelRequested: false,
      retryable: true,
      attemptCount: 0,
      createdAt: '',
      updatedAt: '',
    })
    const store = useAudioCreationStore()

    const first = store.submitSingle(input)
    const second = store.submitSingle(input)
    expect(createSingleAudio).toHaveBeenCalledTimes(1)
    accept?.({ audioId: 8, jobId: 13 })
    await Promise.all([first, second])

    expect(store.active).toBe(true)
    expect(localStorage.getItem('listening.audioCreation')).toContain('"audioId":8')
    store.stopPolling()
  })

  it('restores a completed audio task', async () => {
    localStorage.setItem(
      'listening.audioCreation',
      JSON.stringify({ audioId: 8, jobId: 13 }),
    )
    vi.mocked(getJob).mockResolvedValue({
      id: 13,
      type: 'audio_synthesis',
      status: 'succeeded',
      progress: 100,
      inputSummary: {},
      result: { type: 'audio', id: 8 },
      cancelRequested: false,
      retryable: true,
      attemptCount: 1,
      createdAt: '',
      updatedAt: '',
    })
    const store = useAudioCreationStore()

    store.resume()
    await vi.waitFor(() => expect(store.completed).toBe(true))

    expect(store.audioId).toBe(8)
  })
})
