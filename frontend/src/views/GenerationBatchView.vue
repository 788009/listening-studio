<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/errors'
import {
  createGenerationBatch,
  getGenerationBatch,
  type GenerationBatch,
  type GenerationBatchStatus,
  type QuestionType,
} from '@/api/generationBatches'
import { listVoices, type Voice } from '@/api/voices'
import SpeakerDefinitionsEditor from '@/components/SpeakerDefinitionsEditor.vue'
import type { SpeakerDraft } from '@/components/dialogueTurnTypes'
import { useI18n } from '@/i18n'
import { useListeningDraftsStore } from '@/stores/listeningDrafts'

type InputMode = 'text' | 'file'

const MAX_COUNT = 20
const questionOptions: { value: QuestionType; label: string; detail: string }[] = [
  { value: 'short_dialogue', label: 'Short dialogue', detail: 'Two-speaker brief exchanges' },
  { value: 'long_dialogue', label: 'Long dialogue', detail: 'Two-speaker extended conversations' },
  { value: 'monologue', label: 'Monologue', detail: 'Single-speaker passages' },
]

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const draftStore = useListeningDraftsStore()
const inputMode = ref<InputMode>('text')
const corpus = ref('')
const corpusFile = ref<File | null>(null)
const encoding = ref('utf-8')
const selectedQuestionType = ref<QuestionType>('short_dialogue')
const questionCount = ref(1)
const speakers = ref<SpeakerDraft[]>([
  { key: 1, name: t('Speaker {position}', { position: 1 }), voiceId: '' },
  { key: 2, name: t('Speaker {position}', { position: 2 }), voiceId: '' },
])
const voices = ref<Voice[]>([])
const batch = ref<GenerationBatch | null>(null)
const loadingOptions = ref(true)
const loadingBatch = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
let pollTimer: number | undefined

const batchId = computed(() => {
  const value = Number(route.params.id)
  return Number.isInteger(value) && value > 0 ? value : null
})
const requiresDialogue = computed(() => selectedQuestionType.value !== 'monologue')

function removeSpeaker(speakerKey: number): void {
  if (speakers.value.length <= 1) return
  speakers.value = speakers.value.filter((speaker) => speaker.key !== speakerKey)
}

function selectFile(event: Event): void {
  corpusFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function validate(): Record<string, number> | null {
  errorMessage.value = ''
  if (!Number.isInteger(questionCount.value) || questionCount.value < 1 || questionCount.value > MAX_COUNT) {
    errorMessage.value = t('Count must be between 1 and {count}', {
      count: MAX_COUNT,
    })
    return null
  }
  if (inputMode.value === 'text' && !corpus.value.trim()) {
    errorMessage.value = t('Enter corpus text')
    return null
  }
  if (inputMode.value === 'file' && !corpusFile.value) {
    errorMessage.value = t('Choose a TXT file')
    return null
  }
  if (inputMode.value === 'file' && !corpusFile.value?.name.toLowerCase().endsWith('.txt')) {
    errorMessage.value = t('Corpus file must use the .txt extension')
    return null
  }
  const result: Record<string, number> = {}
  const names = new Set<string>()
  for (const speaker of speakers.value) {
    const name = speaker.name.trim()
    const normalizedName = name.normalize('NFKC').toLocaleLowerCase()
    const voiceId = Number(speaker.voiceId)
    if (!name || names.has(normalizedName) || !Number.isInteger(voiceId) || voiceId < 1) {
      errorMessage.value = t('Complete each speaker with a unique name and voice')
      return null
    }
    names.add(normalizedName)
    result[name] = voiceId
  }
  if (speakers.value.length < (requiresDialogue.value ? 2 : 1)) {
    errorMessage.value = t('Dialogue types require at least two speakers')
    return null
  }
  return result
}

async function submit(): Promise<void> {
  const speakerVoiceMap = validate()
  if (!speakerVoiceMap) return
  submitting.value = true
  try {
    const accepted = await createGenerationBatch({
      corpus: inputMode.value === 'text' ? corpus.value.trim() : undefined,
      file: inputMode.value === 'file' ? corpusFile.value ?? undefined : undefined,
      encoding: inputMode.value === 'file' ? encoding.value : undefined,
      questionType: selectedQuestionType.value,
      count: questionCount.value,
      speakerVoiceMap,
    })
    await router.replace({ name: 'generation-batch', params: { id: accepted.batchId } })
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Batch could not be submitted')
  } finally {
    submitting.value = false
  }
}

async function loadOptions(): Promise<void> {
  loadingOptions.value = true
  try {
    const response = await listVoices({ language: locale.value })
    voices.value = response.items.filter((voice) => voice.status === 'ready')
    const firstVoice = voices.value[0]
    if (firstVoice) {
      speakers.value = speakers.value.map((speaker) => ({
        ...speaker,
        voiceId: speaker.voiceId || String(firstVoice.id),
      }))
    }
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Generation options could not be loaded')
  } finally {
    loadingOptions.value = false
  }
}

async function loadBatch(): Promise<void> {
  if (!batchId.value) {
    batch.value = null
    return
  }
  loadingBatch.value = batch.value === null
  try {
    const result = await getGenerationBatch(batchId.value)
    batch.value = result
    if (result.status === 'completed') {
      const completedDrafts = result.items.filter((item) => item.draft)
      if (completedDrafts.length === 0) throw new Error('Completed batch has no drafts')
      draftStore.setBatch(result)
      await router.replace({ name: 'create', query: { batch: String(result.id) } })
      return
    }
    schedulePoll(result.status)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Batch could not be loaded')
  } finally {
    loadingBatch.value = false
  }
}

function schedulePoll(status: GenerationBatchStatus): void {
  stopPolling()
  if (status === 'pending' || status === 'processing') {
    pollTimer = window.setTimeout(() => void loadBatch(), 1000)
  }
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

watch(batchId, () => {
  stopPolling()
  batch.value = null
  void loadBatch()
})
onMounted(() => {
  void loadOptions()
  void loadBatch()
})
onUnmounted(stopPolling)
</script>

<template>
  <section aria-labelledby="batch-page-title" class="page-shell min-w-0">
    <div class="page-heading">
      <div class="min-w-0">
        <p class="eyebrow">{{ t('Teacher workspace') }}</p>
        <h1 id="batch-page-title" class="break-words text-3xl font-semibold">{{ t('Batch generation') }}</h1>
      </div>
    </div>

    <p v-if="errorMessage" role="alert" class="mt-6 border border-danger/30 bg-surface px-5 py-4 text-sm text-danger">{{ errorMessage }}</p>

    <div v-if="batchId" class="mt-6 border border-line bg-surface px-5 py-7 shadow-panel">
      <div class="flex items-center justify-between gap-5">
        <div>
          <h2 class="text-base font-semibold">{{ t('Generating drafts') }}</h2>
          <p class="mt-1 text-sm text-muted">{{ t('Content and topic suggestions are being prepared') }}</p>
        </div>
        <span class="text-sm font-medium tabular-nums">{{ batch?.progress ?? 0 }}%</span>
      </div>
      <div class="mt-5 h-2 overflow-hidden bg-canvas" role="progressbar" :aria-valuenow="batch?.progress ?? 0" aria-valuemin="0" aria-valuemax="100">
        <div class="h-full bg-accent transition-[width]" :style="{ width: `${batch?.progress ?? 0}%` }" />
      </div>
      <p v-if="loadingBatch" class="mt-4 text-sm text-muted">{{ t('Loading batch') }}</p>
      <p v-if="batch?.status === 'failed'" class="mt-4 text-sm text-danger">{{ batch.errorSummary || t('Generation failed') }}</p>
    </div>

    <form v-else class="mt-6 min-w-0 overflow-hidden border border-line bg-surface shadow-panel" @submit.prevent="submit">
      <section class="border-b border-line px-5 py-6">
        <h2 class="text-base font-semibold">{{ t('Corpus') }}</h2>
        <div class="mt-5 inline-grid h-10 grid-cols-2 border border-line" :aria-label="t('Corpus input mode')">
          <button type="button" class="px-4 text-sm font-medium" :class="inputMode === 'text' ? 'bg-ink text-white' : 'text-muted'" @click="inputMode = 'text'">{{ t('Text input') }}</button>
          <button type="button" class="px-4 text-sm font-medium" :class="inputMode === 'file' ? 'bg-ink text-white' : 'text-muted'" @click="inputMode = 'file'">{{ t('TXT file') }}</button>
        </div>
        <textarea v-if="inputMode === 'text'" id="corpus-text" v-model="corpus" rows="9" class="mt-4 w-full resize-y border border-line px-3 py-3 text-sm leading-6 focus:border-accent focus:outline-none" :placeholder="t('Paste source material here')" />
        <div v-else class="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
          <input id="corpus-file" type="file" accept=".txt,text/plain" class="h-10 min-w-0 border border-line px-3 py-2 text-sm" @change="selectFile" />
          <select v-model="encoding" class="h-10 border border-line bg-surface px-3 text-sm">
            <option value="utf-8">UTF-8</option><option value="utf-8-sig">UTF-8 BOM</option><option value="utf-16">UTF-16</option>
          </select>
        </div>
      </section>

      <section class="border-b border-line px-5 py-6">
        <fieldset>
          <legend class="text-base font-semibold">{{ t('Question type') }}</legend>
          <div class="mt-4 grid overflow-hidden border border-line sm:grid-cols-3">
            <label
              v-for="option in questionOptions"
              :key="option.value"
              :for="`question-type-${option.value}`"
              class="relative min-h-24 cursor-pointer border-b border-line px-4 py-4 transition-colors last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0"
              :class="selectedQuestionType === option.value ? 'bg-accent-soft text-ink' : 'bg-surface text-muted hover:bg-canvas'"
            >
              <span class="flex items-center justify-between gap-3">
                <span class="text-sm font-semibold">{{ t(option.label) }}</span>
                <input
                  :id="`question-type-${option.value}`"
                  v-model="selectedQuestionType"
                  type="radio"
                  name="question-type"
                  :value="option.value"
                  class="h-4 w-4 shrink-0 accent-accent"
                />
              </span>
              <span class="mt-2 block text-xs leading-5 text-muted">{{ t(option.detail) }}</span>
            </label>
          </div>
          <div class="mt-5 flex flex-col gap-2 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
            <label for="question-count" class="text-sm font-medium">{{ t('Quantity') }}</label>
            <input
              id="question-count"
              v-model.number="questionCount"
              type="number"
              min="1"
              :max="MAX_COUNT"
              class="h-10 w-full border border-line bg-surface px-3 text-sm tabular-nums focus:border-accent focus:outline-none sm:w-32"
            />
          </div>
        </fieldset>
      </section>

      <SpeakerDefinitionsEditor v-if="!loadingOptions && voices.length" v-model="speakers" :voices="voices" @remove="removeSpeaker" />
      <div v-else class="border-b border-line px-5 py-8 text-sm text-muted">{{ loadingOptions ? t('Loading options') : t('No ready voices are available') }}</div>

      <div class="flex items-center justify-end px-5 py-5">
        <button type="submit" :disabled="submitting || loadingOptions || voices.length === 0" class="inline-flex h-10 items-center gap-2 bg-ink px-5 text-sm font-medium text-white hover:bg-accent disabled:opacity-50">
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M8 5v14l11-7Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" /></svg>
          {{ submitting ? t('Submitting') : t('Generate drafts') }}
        </button>
      </div>
    </form>
  </section>
</template>
