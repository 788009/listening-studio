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
import ActiveJobProgress from '@/components/ActiveJobProgress.vue'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import DialogueTurnsEditor from '@/components/DialogueTurnsEditor.vue'
import SpeakerDefinitionsEditor from '@/components/SpeakerDefinitionsEditor.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import type {
  DialogueTurnDraft,
  SpeakerDraft,
} from '@/components/dialogueTurnTypes'
import type { TagTranslation } from '@/api/voices'
import { useAudioCreationStore } from '@/stores/audioCreation'
import { useI18n } from '@/i18n'

type CreationTagType = 'topic' | 'category'

const route = useRoute()
const { locale, t } = useI18n()
const creation = useAudioCreationStore()
const title = ref('')
const speakers = ref<SpeakerDraft[]>([])
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

const progressStages = computed(() => [
  { threshold: 5, label: t('Preparing audio generation') },
  { threshold: 20, label: t('Generating speech') },
  { threshold: 82, label: t('Processing generated audio') },
  { threshold: 88, label: t('Saving audio') },
])

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

function newSpeaker(voiceId?: string): SpeakerDraft {
  const nextKey = Math.max(0, ...speakers.value.map((speaker) => speaker.key)) + 1
  return {
    key: nextKey,
    name: '',
    voiceId: voiceId ?? (voices.value[0] ? String(voices.value[0].id) : ''),
  }
}

function newTurn(speakerKey?: number): DialogueTurnDraft {
  const nextKey = Math.max(0, ...turns.value.map((turn) => turn.key)) + 1
  return {
    key: nextKey,
    speakerKey: speakerKey ?? speakers.value[0]?.key ?? '',
    text: '',
  }
}

function removeSpeaker(speakerKey: number): void {
  if (speakers.value.length <= 1) return
  speakers.value = speakers.value.filter((speaker) => speaker.key !== speakerKey)
  const fallbackKey = speakers.value[0]?.key ?? ''
  turns.value = turns.value.map((turn) =>
    turn.speakerKey === speakerKey ? { ...turn, speakerKey: fallbackKey } : turn,
  )
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
    const voiceId = selected
      ? String(selected.id)
      : voices.value[0]
        ? String(voices.value[0].id)
        : ''
    if (speakers.value.length === 0) speakers.value = [newSpeaker(voiceId)]
    if (turns.value.length === 0) turns.value = [newTurn(speakers.value[0]?.key)]
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
  const normalizedSpeakers = speakers.value.map((speaker) => ({
    ...speaker,
    name: speaker.name.trim(),
    voiceId: Number(speaker.voiceId),
  }))
  const normalizedNames = normalizedSpeakers.map((speaker) =>
    speaker.name.normalize('NFKC').toLocaleLowerCase(),
  )
  if (
    normalizedSpeakers.some(
      (speaker) => !speaker.name || !Number.isInteger(speaker.voiceId) || speaker.voiceId < 1,
    ) || new Set(normalizedNames).size !== normalizedNames.length
  ) {
    formError.value = t('Complete each speaker with a unique name and voice')
    return
  }

  const content = turns.value.map((turn) => {
    const speaker = normalizedSpeakers.find((item) => item.key === turn.speakerKey)
    return {
      speakerKey: turn.speakerKey,
      voiceId: speaker?.voiceId ?? 0,
      speakerDisplayName: speaker?.name ?? '',
      text: turn.text.trim(),
    }
  })
  if (
    content.some(
      (turn) =>
        !Number.isInteger(turn.voiceId) ||
        turn.voiceId < 1 ||
        !turn.speakerDisplayName ||
        !turn.text,
    )
  ) {
    formError.value = t('Select a speaker and enter text for every item')
    return
  }

  const speakerKeys = new Set(content.map((item) => item.speakerKey))
  if (speakerKeys.size === 1) {
    const item = content[0]
    if (!item) return
    await creation.submitSingle({
      title: normalizedTitle,
      text: content.map((turn) => turn.text).join('\n'),
      voiceId: item.voiceId,
      speakerDisplayName: item.speakerDisplayName,
      tagIds: selectedTagIds.value,
      visibility: visibility.value,
    })
    return
  }
  await creation.submitDialogue({
    title: normalizedTitle,
    utterances: content.map((utterance) => ({
      voiceId: utterance.voiceId,
      speakerDisplayName: utterance.speakerDisplayName,
      text: utterance.text,
    })),
    tagIds: selectedTagIds.value,
    visibility: visibility.value,
  })
}

function startAnother(): void {
  creation.reset()
  title.value = ''
  speakers.value = [newSpeaker()]
  turns.value = [newTurn(speakers.value[0]?.key)]
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
  <section aria-labelledby="create-title" class="page-shell min-w-0">
    <div class="page-heading">
      <div class="min-w-0">
        <p class="eyebrow">{{ t('Teacher workspace') }}</p>
        <h1 id="create-title" class="break-words text-3xl font-semibold">{{ t('Create listening') }}</h1>
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

    <div v-if="creation.active" class="mt-6 rounded-lg border border-line bg-surface px-5 py-8 shadow-panel">
      <ActiveJobProgress
        :progress="creation.job?.progress ?? 0"
        :queued="creation.job?.status === 'queued'"
        :queued-label="t('Waiting for processing')"
        :stages="progressStages"
        :task-label="t('Task {id}', { id: creation.jobId ?? '' })"
        :progress-label="t('Audio generation progress')"
      />
    </div>

    <div v-else-if="creation.completed && creation.audioId" class="mt-6 rounded-lg border border-line bg-surface px-5 py-9 shadow-panel">
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

    <form v-else class="mt-6 min-w-0 overflow-hidden rounded-lg border border-line bg-surface shadow-panel" @submit.prevent="submit">
      <div v-if="creation.failed" class="border-b border-line px-5 py-4">
        <p role="alert" class="break-words text-sm text-danger">
          {{ failureMessage || t('Audio generation failed') }}
        </p>
      </div>

      <div class="border-b border-line px-5 py-6">
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
      </div>

      <div v-if="loadingOptions" class="border-b border-line px-5 py-12 text-sm text-muted">{{ t('Loading options') }}</div>
      <div v-else-if="voices.length === 0" class="border-b border-line px-5 py-10">
        <p class="text-sm text-muted">{{ t('No ready voices are available') }}</p>
        <RouterLink to="/voices/create" class="mt-3 inline-block text-sm font-medium text-accent underline">{{ t('Create voice') }}</RouterLink>
      </div>

      <SpeakerDefinitionsEditor
        v-if="!loadingOptions && voices.length > 0"
        v-model="speakers"
        :voices="voices"
        @remove="removeSpeaker"
      />

      <DialogueTurnsEditor
        v-if="!loadingOptions && voices.length > 0"
        v-model="turns"
        :speakers="speakers"
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
