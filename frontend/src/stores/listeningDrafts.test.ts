import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useListeningDraftsStore } from './listeningDrafts'


const batch = {
  id: 9,
  jobId: 10,
  questionTypeCounts: { monologue: 1 },
  status: 'completed' as const,
  progress: 100,
  tags: [{ id: 4, type: 'topic' as const, englishValue: 'travel' }],
  speakerVoices: [{ speaker: 'Narrator', voiceId: 2 }],
  items: [
    {
      id: 1,
      position: 0,
      status: 'completed' as const,
      attemptCount: 1,
      draft: {
        questionType: 'monologue' as const,
        title: 'Report',
        utterances: [{ speakerDisplayName: 'Narrator', voiceId: 2, text: 'Text' }],
        questions: [{ prompt: 'Question?', correctAnswers: ['A'], incorrectAnswers: ['B'] }],
      },
    },
  ],
  createdAt: '',
  updatedAt: '',
}

describe('listening draft store', () => {
  beforeEach(() => {
    sessionStorage.clear()
    setActivePinia(createPinia())
  })

  it('stores generated drafts with suggested tags and restores them', () => {
    const store = useListeningDraftsStore()
    store.setBatch(batch)
    expect(store.activeDraft?.tagIds).toEqual([4])
    expect(store.activeDraft?.title).toBe('Report')

    setActivePinia(createPinia())
    const restored = useListeningDraftsStore()
    expect(restored.sourceBatchId).toBe(9)
    expect(restored.activeDraft?.questions[0]?.prompt).toBe('Question?')
  })

  it('updates and removes individual drafts', () => {
    const store = useListeningDraftsStore()
    store.setBatch(batch)
    store.updateDraft(0, { ...store.drafts[0]!, title: 'Edited' })
    expect(store.activeDraft?.title).toBe('Edited')
    store.removeDraft(0)
    expect(store.drafts).toEqual([])
    expect(store.sourceBatchId).toBeNull()
  })
})
