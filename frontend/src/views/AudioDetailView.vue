<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  audioMediaPath,
  createAudioTag,
  deleteAudio,
  getAudio,
  listAudioTags,
  updateAudio,
  type Audio,
  type AudioTag,
  type AudioTagType,
  type AudioQuestionInput,
  type ResourceVisibility,
} from '@/api/audios'
import type { TagTranslation } from '@/api/voices'
import { ApiError } from '@/api/errors'
import AudioTagLines from '@/components/AudioTagLines.vue'
import AudioQuestionsDisplay from '@/components/AudioQuestionsDisplay.vue'
import AudioQuestionsEditor from '@/components/AudioQuestionsEditor.vue'
import SpeakerVoiceLines from '@/components/SpeakerVoiceLines.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import ResourceStatus from '@/components/ResourceStatus.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { locale, t } = useI18n()
const audio = ref<Audio | null>(null)
const loading = ref(true)
const editing = ref(false)
const saving = ref(false)
const deleting = ref(false)
const confirmDelete = ref(false)
const errorMessage = ref('')
const formError = ref('')
const title = ref('')
const visibility = ref<ResourceVisibility>('private')
const tags = ref<AudioTag[]>([])
const selectedTagIds = ref<number[]>([])
const questions = ref<AudioQuestionInput[]>([])
const tagsLoading = ref(false)
const creatingTagType = ref<EditableAudioTagType | null>(null)
const tagDialogType = ref<EditableAudioTagType | null>(null)
const tagDialogInitialEnglishValue = ref('')
const tagDialogError = ref('')

type EditableAudioTagType = Extract<AudioTagType, 'topic' | 'category'>

const audioId = computed(() => Number(route.params.id))
const isOwner = computed(
  () =>
    audio.value !== null &&
    audio.value.author.userId.toLowerCase() === auth.user?.userId?.toLowerCase(),
)
const canDelete = computed(
  () =>
    isOwner.value ||
    (auth.isAdmin && audio.value?.visibility === 'public'),
)
const orderedUtterances = computed(() =>
  [...(audio.value?.utterances ?? [])].sort((left, right) => left.position - right.position),
)
const tagGroups = computed(() => [
  { label: 'Topics', type: 'topic' as const },
  { label: 'Categories', type: 'category' as const },
])

function resetForm(current: Audio): void {
  title.value = current.title
  visibility.value = current.visibility
  selectedTagIds.value = current.tags
    .filter((tag) => tag.type === 'topic' || tag.type === 'category')
    .map((tag) => tag.id)
  questions.value = (current.questions ?? []).map((question) => ({
    prompt: question.prompt,
    correctAnswers: [...question.correctAnswers],
    incorrectAnswers: [...question.incorrectAnswers],
  }))
}

function normalizedQuestions(): AudioQuestionInput[] | null {
  if (
    questions.value.some(
      (question) =>
        !question.prompt.trim() ||
        question.correctAnswers.length === 0 ||
        question.incorrectAnswers.length === 0 ||
        question.correctAnswers.some((answer) => !answer.trim()) ||
        question.incorrectAnswers.some((answer) => !answer.trim()),
    )
  ) {
    formError.value = t('Complete every question and answer')
    return null
  }
  return questions.value.map((question) => ({
    prompt: question.prompt.trim(),
    correctAnswers: question.correctAnswers.map((answer) => answer.trim()),
    incorrectAnswers: question.incorrectAnswers.map((answer) => answer.trim()),
  }))
}

async function loadAudio(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  editing.value = false
  try {
    if (!Number.isInteger(audioId.value) || audioId.value < 1) {
      throw new TypeError('Audio not found')
    }
    audio.value = await getAudio(audioId.value, locale.value)
    resetForm(audio.value)
  } catch (error) {
    audio.value = null
    errorMessage.value = error instanceof ApiError ? error.message : t('Audio not found')
  } finally {
    loading.value = false
  }
}

async function beginEditing(): Promise<void> {
  if (!audio.value) return
  resetForm(audio.value)
  formError.value = ''
  editing.value = true
  tagsLoading.value = true
  try {
    tags.value = await listAudioTags(locale.value)
  } catch (error) {
    formError.value = error instanceof ApiError ? error.message : t('Tags could not be loaded')
  } finally {
    tagsLoading.value = false
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

function openTagDialog(type: EditableAudioTagType, query: string): void {
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

async function saveAudio(): Promise<void> {
  if (!audio.value) return
  const normalizedQuestionValues = normalizedQuestions()
  if (!normalizedQuestionValues) return
  saving.value = true
  formError.value = ''
  try {
    audio.value = await updateAudio(audio.value.id, {
      title: title.value,
      visibility: visibility.value,
      tagIds: selectedTagIds.value,
      questions: normalizedQuestionValues,
    })
    editing.value = false
    resetForm(audio.value)
  } catch (error) {
    formError.value = error instanceof ApiError ? error.message : t('Audio could not be saved')
  } finally {
    saving.value = false
  }
}

async function removeAudio(): Promise<void> {
  if (!audio.value) return
  deleting.value = true
  formError.value = ''
  try {
    await deleteAudio(audio.value.id)
    await router.push({ name: 'library' })
  } catch (error) {
    confirmDelete.value = false
    formError.value = error instanceof ApiError ? error.message : t('Audio could not be deleted')
  } finally {
    deleting.value = false
  }
}

watch(() => route.params.id, loadAudio, { immediate: true })
</script>

<template>
  <section class="page-shell" aria-labelledby="audio-title">
    <p v-if="loading" class="border-b border-line py-12 text-sm text-muted">{{ t('Loading audio') }}</p>
    <div v-else-if="errorMessage && !audio" class="border-b border-line py-12">
      <p role="alert" class="text-sm text-danger">{{ errorMessage }}</p>
      <RouterLink to="/audio" class="mt-4 inline-block text-sm font-medium text-accent underline">
        {{ t('Back to library') }}
      </RouterLink>
    </div>

    <template v-else-if="audio">
      <div class="page-heading">
        <div class="min-w-0">
          <RouterLink to="/audio" class="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Library') }}
          </RouterLink>
          <h1 id="audio-title" class="break-words text-3xl font-semibold">{{ audio.title }}</h1>
          <RouterLink
            :to="`/user/${audio.author.userId}`"
            class="mt-1 inline-block break-words text-sm text-muted hover:text-ink"
          >
            {{ audio.author.username || audio.author.userId }}
          </RouterLink>
        </div>
        <div v-if="!editing" class="flex flex-wrap items-center gap-2">
          <RouterLink
            v-if="auth.profileComplete && audio.visibility === 'public'"
            :to="{ name: 'create', query: { fromAudio: String(audio.id) } }"
            class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
              <path d="M4 4h6M4 4v6" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Create from this audio') }}
          </RouterLink>
          <button
            v-if="isOwner"
            type="button"
            class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
            @click="beginEditing"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="m4 16-1 5 5-1L19 9l-4-4L4 16Z" stroke="currentColor" stroke-width="2" />
              <path d="m13 7 4 4" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Edit') }}
          </button>
          <button
            v-if="canDelete && !isOwner"
            type="button"
            class="inline-flex h-9 items-center gap-2 border border-danger/40 px-3 text-sm font-medium text-danger hover:border-danger"
            @click="confirmDelete = true"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Delete audio') }}
          </button>
        </div>
      </div>

      <p v-if="formError && !editing" role="alert" class="border-b border-line py-4 text-sm text-danger">
        {{ formError }}
      </p>

      <form v-if="editing" class="mt-6 rounded-lg border border-line bg-surface p-5 shadow-panel" @submit.prevent="saveAudio">
        <div class="grid gap-5 sm:grid-cols-[minmax(0,1fr)_12rem]">
          <div>
            <label for="audio-title-input" class="mb-1 block text-sm font-medium">{{ t('Title') }}</label>
            <input
              id="audio-title-input"
              v-model="title"
              required
              maxlength="200"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            />
          </div>
          <div>
            <label for="audio-visibility" class="mb-1 block text-sm font-medium">{{ t('Visibility') }}</label>
            <select
              id="audio-visibility"
              v-model="visibility"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            >
              <option value="private">{{ t('Private') }}</option>
              <option value="public" :disabled="audio.status !== 'ready'">{{ t('Public') }}</option>
            </select>
          </div>
          <div class="grid min-w-0 gap-5 sm:col-span-2 md:grid-cols-2">
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
          <AudioQuestionsEditor v-model="questions" embedded class="sm:col-span-2" />
        </div>
        <p v-if="formError" role="alert" class="mt-4 text-sm text-danger">{{ formError }}</p>
        <div class="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
          <button
            type="button"
            class="inline-flex h-9 items-center gap-2 text-sm font-medium text-danger hover:underline"
            @click="confirmDelete = true"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Delete audio') }}
          </button>
          <div class="flex gap-2">
            <button
              type="button"
              class="h-9 border border-line px-3 text-sm font-medium hover:border-ink"
              @click="editing = false"
            >
              {{ t('Cancel') }}
            </button>
            <button
              type="submit"
              :disabled="saving || tagsLoading"
              class="h-9 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-60"
            >
              {{ saving ? t('Saving') : t('Save') }}
            </button>
          </div>
        </div>
      </form>

      <div class="mt-6 grid overflow-hidden rounded-lg border border-line bg-surface shadow-panel md:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="min-w-0 border-b border-line px-4 py-6 md:border-b-0 md:border-r md:px-5">
          <h2 class="text-sm font-semibold">{{ t('Playback') }}</h2>
          <audio
            v-if="audio.status === 'ready'"
            class="mt-4 h-10 w-full max-w-xl"
            controls
            preload="metadata"
            :src="audioMediaPath(audio.id)"
          ></audio>
          <p v-else class="mt-4 text-sm text-muted">{{ t('Audio unavailable') }}</p>
        </div>
        <dl class="px-4 py-5 md:px-5">
          <dt class="text-sm text-muted">{{ t('Status') }}</dt>
          <dd class="mt-2"><ResourceStatus :status="audio.status" /></dd>
        </dl>
      </div>

      <div class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]">
        <h2 class="text-sm font-semibold">{{ t('Tags') }}</h2>
        <div class="space-y-5">
          <AudioTagLines :tags="audio.tags" :include-voice="false" search-path="/audio" grouped />
          <dl>
            <SpeakerVoiceLines :utterances="audio.utterances" />
          </dl>
        </div>
      </div>

      <div
        v-if="(audio.questions?.length ?? 0) > 0"
        class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]"
      >
        <h2 class="text-sm font-semibold">{{ t('Questions') }}</h2>
        <AudioQuestionsDisplay :questions="audio.questions ?? []" />
      </div>

      <div class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]">
        <h2 class="text-sm font-semibold">{{ t('Text') }}</h2>
        <ol v-if="orderedUtterances.length > 0" class="min-w-0 space-y-4">
          <li
            v-for="utterance in orderedUtterances"
            :key="utterance.position"
            class="grid min-w-0 gap-1 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-4"
          >
            <span class="break-words text-sm font-medium">{{ utterance.speakerDisplayName }}</span>
            <p class="min-w-0 break-words text-sm leading-6">{{ utterance.text }}</p>
          </li>
        </ol>
        <p v-else class="min-w-0 whitespace-pre-wrap break-words text-sm leading-6">{{ audio.text }}</p>
      </div>

      <div v-if="isOwner && audio.errorSummary" class="border-b border-line py-6">
        <h2 class="text-sm font-semibold text-danger">{{ t('Generation error') }}</h2>
        <p class="mt-2 break-words text-sm text-muted">{{ audio.errorSummary }}</p>
      </div>
    </template>

    <ConfirmDialog
      :open="confirmDelete"
      :title="t('Delete audio')"
      :busy="deleting"
      confirm-label="Delete"
      @close="confirmDelete = false"
      @confirm="removeAudio"
    >
      <p>{{ t('This audio and its stored file will be removed.') }}</p>
    </ConfirmDialog>

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
