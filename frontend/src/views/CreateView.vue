<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import {
  createAudioTag,
  listAudioCreationTags,
  type AudioTag,
  type ResourceVisibility,
} from '@/api/audios'
import { listVoices, type Voice } from '@/api/voices'
import { ApiError } from '@/api/errors'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import CreationModeControl from '@/components/CreationModeControl.vue'
import DialogueTurnsEditor from '@/components/DialogueTurnsEditor.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import type { DialogueTurnDraft } from '@/components/dialogueTurnTypes'
import type { TagTranslation } from '@/api/voices'
import { useAudioCreationStore } from '@/stores/audioCreation'
import { useI18n } from '@/i18n'

type CreationMode = 'single' | 'dialogue'
type CreationTagType = 'topic' | 'category'

const route = useRoute()
const { locale, t } = useI18n()
const creation = useAudioCreationStore()
const mode = ref<CreationMode>('single')
const title = ref('')
const singleVoiceId = ref('')
const singleText = ref('')
const turns = ref<DialogueTurnDraft[]>([])
const visibility = ref<ResourceVisibility>('private')
const selectedTagIds = ref<number[]>([])
const voices = ref<Voice[]>([])
const tags = ref<AudioTag[]>([])
const creatingTagType = ref<CreationTagType | null>(null)
const tagDialogType = ref<CreationTagType | null>(null)
const tagDialogInitialEnglishValue = ref('')
const tagDialogError = ref('')
const loadingOptions = ref(true)
const formError = ref('')

const tagGroups = computed(() => [
  {
    label: 'Topics',
    type: 'topic' as const,
  },
  {
    label: 'Categories',
    type: 'category' as const,
  },
])
const failureMessage = computed(
  () => creation.job?.errorSummary || creation.errorMessage,
)

function newTurn(): DialogueTurnDraft {
  const voiceId = voices.value[0] ? String(voices.value[0].id) : ''
  return {
    key: 1,
    voiceId,
    speaker: '',
    text: '',
  }
}

function selectTag(tagId: number): void {
  if (!selectedTagIds.value.includes(tagId)) {
    selectedTagIds.value = [...selectedTagIds.value, tagId]
  }
}

function removeTag(tagId: number): void {
  selectedTagIds.value = selectedTagIds.value.filter((id) => id !== tagId)
}

function openTagDialog(type: CreationTagType, query: string): void {
  tagDialogType.value = type
  tagDialogInitialEnglishValue.value = query
  tagDialogError.value = ''
}

function closeTagDialog(): void {
  if (creatingTagType.value !== null) return
  tagDialogType.value = null
  tagDialogInitialEnglishValue.value = ''
  tagDialogError.value = ''
}

async function createAndAddTag(input: {
  englishValue: string
  translations: TagTranslation[]
}): Promise<void> {
  if (tagDialogType.value === null || creatingTagType.value !== null) return
  const type = tagDialogType.value
  creatingTagType.value = type
  tagDialogError.value = ''
  try {
    const tag = await createAudioTag({ type, ...input })
    tags.value = [...tags.value, tag]
    selectTag(tag.id)
    tagDialogType.value = null
    tagDialogInitialEnglishValue.value = ''
  } catch (error) {
    tagDialogError.value =
      error instanceof ApiError ? error.message : t('Tag could not be created')
  } finally {
    creatingTagType.value = null
  }
}

async function loadOptions(): Promise<void> {
  loadingOptions.value = true
  formError.value = ''
  try {
    const [voiceResponse, tagResponse] = await Promise.all([
      listVoices({ language: locale.value }),
      listAudioCreationTags(locale.value),
    ])
    voices.value = voiceResponse.items.filter((voice) => voice.status === 'ready')
    tags.value = tagResponse
    const requestedVoice = Number(route.query.voice)
    const selected = voices.value.find((voice) => voice.id === requestedVoice)
    singleVoiceId.value = selected
      ? String(selected.id)
      : voices.value[0]
        ? String(voices.value[0].id)
        : ''
    if (turns.value.length === 0) turns.value = [newTurn()]
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Creation options could not be loaded')
  } finally {
    loadingOptions.value = false
  }
}

async function submit(): Promise<void> {
  formError.value = ''
  const normalizedTitle = title.value.trim()
  if (!normalizedTitle) {
    formError.value = t('Enter a title')
    return
  }
  if (mode.value === 'single') {
    const voiceId = Number(singleVoiceId.value)
    if (!Number.isInteger(voiceId) || !singleText.value.trim()) {
      formError.value = t('Choose a voice and enter listening text')
      return
    }
    await creation.submitSingle({
      title: normalizedTitle,
      text: singleText.value.trim(),
      voiceId,
      tagIds: selectedTagIds.value,
      visibility: visibility.value,
    })
    return
  }

  const utterances = turns.value.map((turn) => ({
    voiceId: Number(turn.voiceId),
    speakerDisplayName: turn.speaker.trim(),
    text: turn.text.trim(),
  }))
  if (
    utterances.some(
      (turn) =>
        !Number.isInteger(turn.voiceId) ||
        turn.voiceId < 1 ||
        !turn.speakerDisplayName ||
        !turn.text,
    )
  ) {
    formError.value = t('Complete the voice, speaker, and text for every turn')
    return
  }
  await creation.submitDialogue({
    title: normalizedTitle,
    utterances,
    tagIds: selectedTagIds.value,
    visibility: visibility.value,
  })
}

function startAnother(): void {
  creation.reset()
  title.value = ''
  singleText.value = ''
  turns.value = [newTurn()]
  selectedTagIds.value = []
  visibility.value = 'private'
  formError.value = ''
}

function leaveCreateView(): void {
  if (creation.completed) {
    creation.reset()
    return
  }
  creation.stopPolling()
}

onMounted(() => {
  creation.resume()
  void loadOptions()
})
onUnmounted(leaveCreateView)
</script>

<template>
  <section aria-labelledby="create-title" class="min-w-0">
    <div class="flex min-w-0 flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div class="min-w-0">
        <p class="mb-1 text-sm font-medium text-accent">{{ t('Teacher workspace') }}</p>
        <h1 id="create-title" class="break-words text-2xl font-semibold">{{ t('Create listening') }}</h1>
      </div>
      <RouterLink
        to="/voices/create"
        class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 3a5 5 0 0 0-5 5v4a5 5 0 0 0 10 0V8a5 5 0 0 0-5-5Z" stroke="currentColor" stroke-width="2" />
          <path d="M4 11v1a8 8 0 0 0 16 0v-1M12 20v2" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Create voice') }}
      </RouterLink>
    </div>

    <div v-if="creation.active" class="border-b border-line bg-surface px-5 py-8">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <p class="break-words text-base font-semibold">
            {{ creation.job?.status === 'running' ? t('Generating audio') : t('Waiting for processing') }}
          </p>
          <p class="mt-1 text-sm text-muted">{{ t('Task {id}', { id: creation.jobId ?? '' }) }}</p>
        </div>
        <span class="shrink-0 text-sm font-medium tabular-nums">{{ creation.job?.progress ?? 0 }}%</span>
      </div>
      <div
        class="mt-5 h-2 overflow-hidden bg-canvas"
        role="progressbar"
        :aria-label="t('Audio generation progress')"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="creation.job?.progress ?? 0"
      >
        <div class="h-full bg-accent" :style="{ width: `${creation.job?.progress ?? 0}%` }" />
      </div>
    </div>

    <div v-else-if="creation.completed && creation.audioId" class="border-b border-line bg-surface px-5 py-9">
      <p class="text-base font-semibold text-success">{{ t('Audio is ready') }}</p>
      <div class="mt-5 flex flex-wrap gap-3">
        <RouterLink
          :to="`/audio/${creation.audioId}`"
          class="inline-flex h-10 items-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent"
        >
          {{ t('View audio') }}
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
          </svg>
        </RouterLink>
        <button type="button" class="h-10 border border-line bg-surface px-4 text-sm font-medium hover:border-ink" @click="startAnother">
          {{ t('Create another') }}
        </button>
      </div>
    </div>

    <form v-else class="min-w-0 border-b border-line bg-surface" @submit.prevent="submit">
      <div v-if="creation.failed" class="border-b border-line px-5 py-4">
        <p role="alert" class="break-words text-sm text-danger">
          {{ failureMessage || t('Audio generation failed') }}
        </p>
      </div>

      <div class="grid min-w-0 gap-5 border-b border-line px-5 py-6 md:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="min-w-0">
          <label for="audio-title" class="mb-1 block text-sm font-medium">{{ t('Title') }}</label>
          <input
            id="audio-title"
            v-model="title"
            type="text"
            required
            maxlength="200"
            class="h-10 w-full min-w-0 border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>
        <div>
          <span class="mb-1 block text-sm font-medium">{{ t('Mode') }}</span>
          <CreationModeControl v-model="mode" />
        </div>
      </div>

      <div v-if="loadingOptions" class="border-b border-line px-5 py-12 text-sm text-muted">{{ t('Loading options') }}</div>
      <div v-else-if="voices.length === 0" class="border-b border-line px-5 py-10">
        <p class="text-sm text-muted">{{ t('No ready voices are available') }}</p>
        <RouterLink to="/voices/create" class="mt-3 inline-block text-sm font-medium text-accent underline">{{ t('Create voice') }}</RouterLink>
      </div>

      <div v-else-if="mode === 'single'" class="grid min-w-0 gap-5 border-b border-line px-5 py-6 md:grid-cols-[18rem_minmax(0,1fr)]">
        <div class="min-w-0">
          <label for="single-voice" class="mb-1 block text-sm font-medium">{{ t('Voice') }}</label>
          <select id="single-voice" v-model="singleVoiceId" class="h-10 w-full min-w-0 border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus">
            <option v-for="voice in voices" :key="voice.id" :value="String(voice.id)">{{ voice.title }}</option>
          </select>
        </div>
        <div class="min-w-0">
          <label for="single-text" class="mb-1 block text-sm font-medium">{{ t('Listening text') }}</label>
          <textarea id="single-text" v-model="singleText" required class="min-h-40 w-full min-w-0 resize-y border border-line p-3 text-sm leading-6 focus:border-accent focus:outline-none focus:shadow-focus" />
        </div>
      </div>

      <DialogueTurnsEditor
        v-else-if="voices.length > 0"
        v-model="turns"
        :voices="voices"
      />

      <div class="grid min-w-0 gap-6 px-5 py-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="grid min-w-0 gap-5 sm:grid-cols-2">
          <ResourceTagPicker
            v-for="group in tagGroups"
            :key="group.type"
            :label="group.label"
            :type="group.type"
            :tags="tags"
            :selected-ids="selectedTagIds"
            @select="selectTag"
            @remove="removeTag"
            @create="openTagDialog(group.type, $event)"
          />
        </div>
        <div class="flex flex-col justify-between gap-6">
          <label class="flex items-start gap-3">
            <input type="checkbox" class="mt-0.5 h-4 w-4 accent-accent" :checked="visibility === 'public'" @change="visibility = ($event.target as HTMLInputElement).checked ? 'public' : 'private'" />
            <span class="text-sm font-medium">{{ t('Publish when ready') }}</span>
          </label>
          <div>
            <p v-if="formError || creation.errorMessage" role="alert" class="mb-3 break-words text-sm text-danger">{{ formError || creation.errorMessage }}</p>
            <button type="submit" :disabled="creation.submitting || creation.active || loadingOptions || voices.length === 0" class="inline-flex h-10 w-full items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50">
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M12 3v18M3 12h18" stroke="currentColor" stroke-width="2" /></svg>
              {{ creation.submitting ? t('Submitting') : creation.failed ? t('Retry generation') : t('Generate audio') }}
            </button>
          </div>
        </div>
      </div>
    </form>

    <TagCreationDialog
      :open="tagDialogType !== null"
      :type="tagDialogType"
      :initial-english-value="tagDialogInitialEnglishValue"
      :busy="creatingTagType !== null"
      :error-message="tagDialogError"
      @close="closeTagDialog"
      @submit="createAndAddTag"
    />
  </section>
</template>
