import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getJob } from '@/api/jobs'
import { createVoiceUpload } from '@/api/voices'
import { useVoiceCreationStore } from './voiceCreation'

vi.mock('@/api/jobs', () => ({
  cancelJob: vi.fn(),
  getJob: vi.fn(),
}))
vi.mock('@/api/voices', () => ({
  createVoiceUpload: vi.fn(),
}))

const queuedJob = {
  id: 13,
  type: 'voice_upload',
  status: 'queued' as const,
  progress: 0,
  inputSummary: { voiceId: 8 },
  cancelRequested: false,
  retryable: true,
  attemptCount: 0,
  createdAt: '2026-07-16T00:00:00Z',
  updatedAt: '2026-07-16T00:00:00Z',
}

describe('voice creation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('prevents duplicate submissions while the first request is pending', async () => {
    let acceptRequest: ((value: { voiceId: number; jobId: number }) => void) | undefined
    vi.mocked(createVoiceUpload).mockReturnValue(
      new Promise((resolve) => {
        acceptRequest = resolve
      }),
    )
    vi.mocked(getJob).mockResolvedValue(queuedJob)
    const store = useVoiceCreationStore()
    const input = {
      title: 'Classroom voice',
      file: new File(['wav'], 'reference.wav'),
      visibility: 'private' as const,
    }

    const first = store.submit(input)
    const second = store.submit(input)
    expect(createVoiceUpload).toHaveBeenCalledTimes(1)
    acceptRequest?.({ voiceId: 8, jobId: 13 })
    await Promise.all([first, second])

    expect(store.active).toBe(true)
    expect(localStorage.getItem('listening.voiceCreation')).toContain('"jobId":13')
    store.stopPolling()
  })

  it('restores a task after a new store instance is created', async () => {
    localStorage.setItem(
      'listening.voiceCreation',
      JSON.stringify({ jobId: 13, voiceId: 8 }),
    )
    vi.mocked(getJob).mockResolvedValue({
      ...queuedJob,
      status: 'succeeded',
      progress: 100,
      result: { type: 'voice', id: 8 },
    })
    const store = useVoiceCreationStore()

    store.resume()
    await vi.waitFor(() => expect(store.completed).toBe(true))

    expect(getJob).toHaveBeenCalledWith(13)
    expect(store.voiceId).toBe(8)
    expect(localStorage.getItem('listening.voiceCreation')).toBeNull()
  })
})
