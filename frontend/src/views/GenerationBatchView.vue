<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { listAudioCreationTags, type AudioTag, type ResourceVisibility } from '@/api/audios'
import { ApiError } from '@/api/errors'
import {
  createGenerationBatch,
  getGenerationBatch,
  retryGenerationBatchItem,
  updateCompletedBatchAudios,
  type GenerationBatch,
  type GenerationBatchItem,
  type GenerationBatchStatus,
  type QuestionType,
} from '@/api/generationBatches'
import { listVoices, type Voice } from '@/api/voices'
import { useAuthStore } from '@/stores/auth'

type InputMode = 'text' | 'file'
interface SpeakerMappingDraft {
  key: number
  speaker: string
  voiceId: string
}

const MAX_COUNT = 20
const questionOptions: { value: QuestionType; label: string }[] = [
  { value: 'multiple_choice', label: 'Multiple choice' },
  { value: 'true_false', label: 'True or false' },
  { value: 'fill_in_blank', label: 'Fill in the blank' },
  { value: 'short_answer', label: 'Short answer' },
]

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const inputMode = ref<InputMode>('text')
const corpus = ref('')
const corpusFile = ref<File | null>(null)
const encoding = ref('utf-8')
const questionTypes = ref<QuestionType[]>(['multiple_choice'])
const count = ref(2)
const selectedTagIds = ref<number[]>([])
const bulkTagIds = ref<number[]>([])
const bulkVisibility = ref<ResourceVisibility>('private')
const mappings = ref<SpeakerMappingDraft[]>([
  { key: 1, speaker: 'Host', voiceId: '' },
  { key: 2, speaker: 'Guest', voiceId: '' },
])
const nextMappingKey = ref(3)
const voices = ref<Voice[]>([])
const tags = ref<AudioTag[]>([])
const batch = ref<GenerationBatch | null>(null)
const loadingOptions = ref(true)
const loadingBatch = ref(false)
const submitting = ref(false)
const applying = ref(false)
const retryingIds = ref<number[]>([])
const errorMessage = ref('')
const actionMessage = ref('')
let pollTimer: number | undefined

const locale = computed(() => auth.user?.locale ?? 'en')
const topicTags = computed(() => tags.value.filter((tag) => tag.type === 'topic'))
const categoryTags = computed(() => tags.value.filter((tag) => tag.type === 'category'))
const completedCount = computed(
  () => batch.value?.items.filter((item) => item.status === 'completed').length ?? 0,
)
const batchId = computed(() => {
  const value = Number(route.params.id)
  return Number.isInteger(value) && value > 0 ? value : null
})

function toggleQuestionType(value: QuestionType): void {
  questionTypes.value = questionTypes.value.includes(value)
    ? questionTypes.value.filter((item) => item !== value)
    : [...questionTypes.value, value]
}

function toggleTag(target: 'submission' | 'bulk', tagId: number): void {
  const current = target === 'submission' ? selectedTagIds.value : bulkTagIds.value
  const updated = current.includes(tagId)
    ? current.filter((id) => id !== tagId)
    : [...current, tagId]
  if (target === 'submission') selectedTagIds.value = updated
  else bulkTagIds.value = updated
}

function addMapping(): void {
  mappings.value.push({ key: nextMappingKey.value++, speaker: '', voiceId: '' })
}

function removeMapping(key: number): void {
  mappings.value = mappings.value.filter((item) => item.key !== key)
}

function selectFile(event: Event): void {
  corpusFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function speakerVoiceMap(): Record<string, number> | null {
  const result: Record<string, number> = {}
  const normalized = new Set<string>()
  for (const mapping of mappings.value) {
    const speaker = mapping.speaker.trim()
    const voiceId = Number(mapping.voiceId)
    const key = speaker.normalize('NFKC').toLocaleLowerCase()
    if (!speaker || !Number.isInteger(voiceId) || voiceId < 1) {
      errorMessage.value = 'Complete every speaker and voice mapping'
      return null
    }
    if (normalized.has(key)) {
      errorMessage.value = 'Speaker roles must be unique'
      return null
    }
    normalized.add(key)
    result[speaker] = voiceId
  }
  if (Object.keys(result).length === 0) {
    errorMessage.value = 'Add at least one speaker and voice mapping'
    return null
  }
  return result
}

function validateSubmission(): Record<string, number> | null {
  if (questionTypes.value.length === 0) {
    errorMessage.value = 'Select at least one question type'
    return null
  }
  if (!Number.isInteger(count.value) || count.value < 1 || count.value > MAX_COUNT) {
    errorMessage.value = `Count must be between 1 and ${MAX_COUNT}`
    return null
  }
  if (inputMode.value === 'text' && !corpus.value.trim()) {
    errorMessage.value = 'Enter corpus text'
    return null
  }
  if (inputMode.value === 'file') {
    if (!corpusFile.value) {
      errorMessage.value = 'Choose a TXT file'
      return null
    }
    if (!corpusFile.value.name.toLocaleLowerCase().endsWith('.txt')) {
      errorMessage.value = 'Corpus file must use the .txt extension'
      return null
    }
  }
  return speakerVoiceMap()
}

async function submit(): Promise<void> {
  errorMessage.value = ''
  actionMessage.value = ''
  const voiceMap = validateSubmission()
  if (!voiceMap) return
  submitting.value = true
  try {
    const accepted = await createGenerationBatch({
      corpus: inputMode.value === 'text' ? corpus.value.trim() : undefined,
      file: inputMode.value === 'file' ? corpusFile.value ?? undefined : undefined,
      encoding: inputMode.value === 'file' ? encoding.value : undefined,
      questionTypes: questionTypes.value,
      count: count.value,
      tagIds: selectedTagIds.value,
      speakerVoiceMap: voiceMap,
    })
    await router.replace({ name: 'generation-batch', params: { id: accepted.batchId } })
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Batch could not be submitted'
  } finally {
    submitting.value = false
  }
}

async function loadOptions(): Promise<void> {
  loadingOptions.value = true
  try {
    const [voiceResponse, tagResponse] = await Promise.all([
      listVoices({ language: locale.value }),
      listAudioCreationTags(locale.value),
    ])
    voices.value = voiceResponse.items.filter((voice) => voice.status === 'ready')
    tags.value = tagResponse
    const firstVoice = voices.value[0]
    if (firstVoice) {
      for (const mapping of mappings.value) {
        if (!mapping.voiceId) mapping.voiceId = String(firstVoice.id)
      }
    }
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Generation options could not be loaded'
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
    if (bulkTagIds.value.length === 0) {
      bulkTagIds.value = result.tags.map((tag) => tag.id)
    }
    schedulePoll(result.status)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : 'Batch could not be loaded'
  } finally {
    loadingBatch.value = false
  }
}

function schedulePoll(status: GenerationBatchStatus): void {
  stopPolling()
  if (status !== 'pending' && status !== 'processing') return
  pollTimer = window.setTimeout(() => void loadBatch(), 1000)
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

async function retry(item: GenerationBatchItem): Promise<void> {
  if (!batch.value) return
  errorMessage.value = ''
  retryingIds.value = [...retryingIds.value, item.id]
  try {
    await retryGenerationBatchItem(batch.value.id, item.id)
    await loadBatch()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : 'Item retry failed'
  } finally {
    retryingIds.value = retryingIds.value.filter((id) => id !== item.id)
  }
}

async function applyCompletedUpdates(): Promise<void> {
  if (!batch.value) return
  applying.value = true
  errorMessage.value = ''
  actionMessage.value = ''
  try {
    const result = await updateCompletedBatchAudios(
      batch.value.id,
      bulkTagIds.value,
      bulkVisibility.value,
    )
    actionMessage.value = `${result.updatedCount} completed audios updated`
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Completed audios could not be updated'
  } finally {
    applying.value = false
  }
}

function statusLabel(status: GenerationBatchStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

function statusClass(status: GenerationBatchStatus): string {
  if (status === 'completed') return 'text-success'
  if (status === 'failed' || status === 'cancelled') return 'text-danger'
  if (status === 'processing') return 'text-warning'
  return 'text-muted'
}

watch(batchId, () => {
  stopPolling()
  batch.value = null
  bulkTagIds.value = []
  void loadBatch()
})

onMounted(() => {
  void loadOptions()
  void loadBatch()
})
onUnmounted(stopPolling)
</script>

<template>
  <section aria-labelledby="batch-page-title" class="min-w-0">
    <div class="flex min-w-0 flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div class="min-w-0">
        <p class="mb-1 text-sm font-medium text-accent">Teacher workspace</p>
        <h1 id="batch-page-title" class="break-words text-2xl font-semibold">Corpus generation</h1>
      </div>
      <RouterLink
        v-if="batch"
        to="/generate"
        class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
        </svg>
        New batch
      </RouterLink>
    </div>

    <p v-if="errorMessage" role="alert" class="border-b border-line bg-surface px-5 py-4 text-sm text-danger">
      {{ errorMessage }}
    </p>

    <div v-if="loadingBatch" class="border-b border-line bg-surface px-5 py-12 text-sm text-muted">
      Loading batch
    </div>

    <template v-else-if="batch">
      <div class="border-b border-line bg-surface px-5 py-6">
        <div class="flex min-w-0 items-start justify-between gap-5">
          <div class="min-w-0">
            <p class="text-base font-semibold">Batch {{ batch.id }}</p>
            <p class="mt-1 text-sm text-muted">
              {{ completedCount }} of {{ batch.requestedCount }} audios ready
            </p>
          </div>
          <span class="shrink-0 text-sm font-medium tabular-nums">{{ batch.progress }}%</span>
        </div>
        <div
          class="mt-5 h-2 overflow-hidden bg-canvas"
          role="progressbar"
          aria-label="Batch generation progress"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="batch.progress"
        >
          <div class="h-full bg-accent" :style="{ width: `${batch.progress}%` }" />
        </div>
        <div class="mt-4 flex items-center gap-2 text-sm font-medium" :class="statusClass(batch.status)">
          <span class="h-2 w-2 bg-current" aria-hidden="true" />
          {{ statusLabel(batch.status) }}
        </div>
        <p v-if="batch.errorSummary" class="mt-2 text-sm text-danger">{{ batch.errorSummary }}</p>
      </div>

      <div class="border-b border-line bg-surface">
        <div class="border-b border-line px-5 py-4">
          <h2 class="text-base font-semibold">Generated items</h2>
        </div>
        <ol class="divide-y divide-line">
          <li
            v-for="item in batch.items"
            :key="item.id"
            class="grid min-w-0 gap-4 px-5 py-5 sm:grid-cols-[2rem_minmax(0,1fr)_auto] sm:items-center"
          >
            <span class="text-sm tabular-nums text-muted">{{ item.position + 1 }}</span>
            <div class="min-w-0">
              <RouterLink
                v-if="item.audioId && item.status === 'completed'"
                :to="`/audio/${item.audioId}`"
                class="break-words text-sm font-semibold hover:text-accent hover:underline"
              >
                {{ item.title || `Audio ${item.audioId}` }}
              </RouterLink>
              <p v-else class="break-words text-sm font-semibold">
                {{ item.title || `Preparing item ${item.position + 1}` }}
              </p>
              <p v-if="item.errorSummary" class="mt-1 break-words text-sm text-danger">
                {{ item.errorSummary }}
              </p>
            </div>
            <div class="flex items-center justify-between gap-4 sm:justify-end">
              <span class="text-sm font-medium" :class="statusClass(item.status)">
                {{ statusLabel(item.status) }}
              </span>
              <button
                v-if="item.status === 'failed'"
                type="button"
                class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink disabled:opacity-50"
                :disabled="retryingIds.includes(item.id)"
                @click="retry(item)"
              >
                <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                  <path d="M20 7v5h-5M4 17v-5h5" stroke="currentColor" stroke-width="2" />
                  <path d="M6.1 9A7 7 0 0 1 18 7l2 5M17.9 15A7 7 0 0 1 6 17l-2-5" stroke="currentColor" stroke-width="2" />
                </svg>
                {{ retryingIds.includes(item.id) ? 'Retrying' : 'Retry' }}
              </button>
            </div>
          </li>
        </ol>
      </div>

      <form
        v-if="completedCount > 0"
        class="border-b border-line bg-surface px-5 py-6"
        @submit.prevent="applyCompletedUpdates"
      >
        <h2 class="text-base font-semibold">Completed audios</h2>
        <div class="mt-5 grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div class="grid min-w-0 gap-5 sm:grid-cols-2">
            <fieldset
              v-for="group in [
                { label: 'Topics', items: topicTags },
                { label: 'Categories', items: categoryTags },
              ]"
              :key="group.label"
              class="min-w-0"
            >
              <legend class="mb-2 text-sm font-medium">{{ group.label }}</legend>
              <div class="space-y-2">
                <label v-for="tag in group.items" :key="tag.id" class="flex min-w-0 items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    class="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                    :checked="bulkTagIds.includes(tag.id)"
                    @change="toggleTag('bulk', tag.id)"
                  />
                  <span class="min-w-0 break-words">{{ tag.displayValue.replace(/_/g, ' ') }}</span>
                </label>
                <p v-if="group.items.length === 0" class="text-sm text-muted">None available</p>
              </div>
            </fieldset>
          </div>
          <div class="flex flex-col justify-between gap-5">
            <label class="flex items-start gap-3">
              <input
                type="checkbox"
                class="mt-0.5 h-4 w-4 accent-accent"
                :checked="bulkVisibility === 'public'"
                @change="bulkVisibility = ($event.target as HTMLInputElement).checked ? 'public' : 'private'"
              />
              <span class="text-sm font-medium">Public visibility</span>
            </label>
            <div>
              <p v-if="actionMessage" class="mb-3 text-sm text-success">{{ actionMessage }}</p>
              <button
                type="submit"
                :disabled="applying || loadingOptions"
                class="h-10 w-full bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
              >
                {{ applying ? 'Applying' : 'Apply to completed' }}
              </button>
            </div>
          </div>
        </div>
      </form>
    </template>

    <form v-else class="min-w-0 border-b border-line bg-surface" @submit.prevent="submit">
      <div class="grid min-w-0 gap-6 border-b border-line px-5 py-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="min-w-0">
          <div class="grid h-10 grid-cols-2 border border-line" aria-label="Corpus input mode">
            <button
              type="button"
              :aria-pressed="inputMode === 'text'"
              :class="inputMode === 'text' ? 'bg-ink text-white' : 'hover:bg-canvas'"
              class="text-sm font-medium"
              @click="inputMode = 'text'"
            >
              Text
            </button>
            <button
              type="button"
              :aria-pressed="inputMode === 'file'"
              :class="inputMode === 'file' ? 'bg-ink text-white' : 'hover:bg-canvas'"
              class="border-l border-line text-sm font-medium"
              @click="inputMode = 'file'"
            >
              TXT file
            </button>
          </div>
          <div class="mt-4">
            <label v-if="inputMode === 'text'" for="corpus-text" class="mb-1 block text-sm font-medium">Corpus text</label>
            <textarea
              v-if="inputMode === 'text'"
              id="corpus-text"
              v-model="corpus"
              class="min-h-56 w-full min-w-0 resize-y border border-line p-3 text-sm leading-6 focus:border-accent focus:outline-none focus:shadow-focus"
            />
            <div v-else class="grid gap-4 sm:grid-cols-[minmax(0,1fr)_12rem]">
              <div class="min-w-0">
                <label for="corpus-file" class="mb-1 block text-sm font-medium">TXT file</label>
                <input
                  id="corpus-file"
                  type="file"
                  accept=".txt,text/plain"
                  class="block h-10 w-full min-w-0 border border-line bg-surface px-2 py-1.5 text-sm file:mr-3 file:border-0 file:bg-canvas file:px-3 file:py-1 file:text-sm"
                  @change="selectFile"
                />
              </div>
              <div>
                <label for="corpus-encoding" class="mb-1 block text-sm font-medium">Encoding</label>
                <select id="corpus-encoding" v-model="encoding" class="h-10 w-full border border-line bg-surface px-3 text-sm">
                  <option value="utf-8">UTF-8</option>
                  <option value="utf-8-sig">UTF-8 with BOM</option>
                  <option value="utf-16">UTF-16</option>
                  <option value="utf-16-le">UTF-16 LE</option>
                  <option value="utf-16-be">UTF-16 BE</option>
                </select>
              </div>
            </div>
          </div>
        </div>
        <div>
          <label for="generation-count" class="mb-1 block text-sm font-medium">Audio count</label>
          <input
            id="generation-count"
            v-model.number="count"
            type="number"
            min="1"
            :max="MAX_COUNT"
            class="h-10 w-full border border-line px-3 text-sm tabular-nums"
          />
          <fieldset class="mt-5">
            <legend class="mb-2 text-sm font-medium">Question types</legend>
            <div class="space-y-2">
              <label v-for="option in questionOptions" :key="option.value" class="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  class="mt-0.5 h-4 w-4 accent-accent"
                  :checked="questionTypes.includes(option.value)"
                  @change="toggleQuestionType(option.value)"
                />
                {{ option.label }}
              </label>
            </div>
          </fieldset>
        </div>
      </div>

      <div class="border-b border-line px-5 py-6">
        <div class="flex items-center justify-between gap-4">
          <h2 class="text-base font-semibold">Speaker voices</h2>
          <button type="button" class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink" @click="addMapping">
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" /></svg>
            Add role
          </button>
        </div>
        <div v-if="loadingOptions" class="py-10 text-sm text-muted">Loading voices</div>
        <div v-else-if="voices.length === 0" class="py-8 text-sm text-muted">No ready voices are available</div>
        <div v-else class="mt-4 space-y-3">
          <div
            v-for="mapping in mappings"
            :key="mapping.key"
            class="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2.5rem]"
          >
            <div class="min-w-0">
              <label :for="`speaker-${mapping.key}`" class="sr-only">Speaker role</label>
              <input :id="`speaker-${mapping.key}`" v-model="mapping.speaker" type="text" maxlength="200" placeholder="Speaker role" class="h-10 w-full min-w-0 border border-line px-3 text-sm" />
            </div>
            <div class="min-w-0">
              <label :for="`speaker-voice-${mapping.key}`" class="sr-only">Voice</label>
              <select :id="`speaker-voice-${mapping.key}`" v-model="mapping.voiceId" class="h-10 w-full min-w-0 border border-line bg-surface px-3 text-sm">
                <option value="" disabled>Select voice</option>
                <option v-for="voice in voices" :key="voice.id" :value="String(voice.id)">{{ voice.title }}</option>
              </select>
            </div>
            <button type="button" class="flex h-10 w-10 items-center justify-center border border-line hover:border-danger hover:text-danger disabled:opacity-40" :disabled="mappings.length === 1" :aria-label="`Remove ${mapping.speaker || 'speaker'} mapping`" title="Remove mapping" @click="removeMapping(mapping.key)">
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M5 12h14" stroke="currentColor" stroke-width="2" /></svg>
            </button>
          </div>
        </div>
      </div>

      <div class="grid min-w-0 gap-6 px-5 py-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="grid min-w-0 gap-5 sm:grid-cols-2">
          <fieldset v-for="group in [{ label: 'Topics', items: topicTags }, { label: 'Categories', items: categoryTags }]" :key="group.label" class="min-w-0">
            <legend class="mb-2 text-sm font-medium">{{ group.label }}</legend>
            <div class="space-y-2">
              <label v-for="tag in group.items" :key="tag.id" class="flex min-w-0 items-start gap-2 text-sm">
                <input type="checkbox" class="mt-0.5 h-4 w-4 accent-accent" :checked="selectedTagIds.includes(tag.id)" @change="toggleTag('submission', tag.id)" />
                <span class="min-w-0 break-words">{{ tag.displayValue.replace(/_/g, ' ') }}</span>
              </label>
              <p v-if="group.items.length === 0" class="text-sm text-muted">None available</p>
            </div>
          </fieldset>
        </div>
        <div class="flex items-end">
          <button
            type="submit"
            :disabled="submitting || loadingOptions || voices.length === 0"
            class="inline-flex h-10 w-full items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M12 3v18M3 12h18" stroke="currentColor" stroke-width="2" /></svg>
            {{ submitting ? 'Submitting' : 'Generate batch' }}
          </button>
        </div>
      </div>
    </form>
  </section>
</template>
