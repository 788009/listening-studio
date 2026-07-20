import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import type { AudioQuestionInput } from '@/api/audios'
import type { GenerationBatch, QuestionType } from '@/api/generationBatches'

const STORAGE_KEY = 'listening-draft-batch-v1'

export interface ListeningDraftUtterance {
  speakerDisplayName: string
  voiceId: number
  text: string
}

export interface ListeningDraft {
  title: string
  questionType: QuestionType
  utterances: ListeningDraftUtterance[]
  questions: AudioQuestionInput[]
  tagIds: number[]
}

interface StoredDraftBatch {
  sourceBatchId: number
  currentIndex: number
  drafts: ListeningDraft[]
}

export const useListeningDraftsStore = defineStore('listeningDrafts', () => {
  const restored = restore()
  const sourceBatchId = ref<number | null>(restored?.sourceBatchId ?? null)
  const currentIndex = ref(restored?.currentIndex ?? 0)
  const drafts = ref<ListeningDraft[]>(restored?.drafts ?? [])
  const activeDraft = computed(() => drafts.value[currentIndex.value] ?? null)

  function setBatch(batch: GenerationBatch): void {
    const tagIds = batch.tags.map((tag) => tag.id)
    sourceBatchId.value = batch.id
    currentIndex.value = 0
    drafts.value = batch.items.flatMap((item) =>
      item.draft ? [{ ...item.draft, tagIds: [...tagIds] }] : [],
    )
    persist()
  }

  function updateDraft(index: number, draft: ListeningDraft): void {
    if (!drafts.value[index]) return
    drafts.value[index] = draft
  }

  function removeDraft(index: number): void {
    if (!drafts.value[index]) return
    drafts.value.splice(index, 1)
    currentIndex.value = Math.min(currentIndex.value, Math.max(0, drafts.value.length - 1))
    if (drafts.value.length === 0) clear()
  }

  function clear(): void {
    sourceBatchId.value = null
    currentIndex.value = 0
    drafts.value = []
    if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(STORAGE_KEY)
  }

  watch(
    [sourceBatchId, currentIndex, drafts],
    persist,
    { deep: true },
  )

  function persist(): void {
      if (sourceBatchId.value === null || drafts.value.length === 0) return
      if (typeof sessionStorage === 'undefined') return
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          sourceBatchId: sourceBatchId.value,
          currentIndex: currentIndex.value,
          drafts: drafts.value,
        } satisfies StoredDraftBatch),
      )
  }

  return {
    sourceBatchId,
    currentIndex,
    drafts,
    activeDraft,
    setBatch,
    updateDraft,
    removeDraft,
    clear,
  }
})

function restore(): StoredDraftBatch | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const parsed = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null') as StoredDraftBatch | null
    if (
      !parsed ||
      !Number.isInteger(parsed.sourceBatchId) ||
      !Number.isInteger(parsed.currentIndex) ||
      !Array.isArray(parsed.drafts)
    ) {
      return null
    }
    return parsed
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
    return null
  }
}
