<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  createVoiceGenderTag,
  deleteVoice,
  getVoice,
  listPublicSampleAudio,
  listVoiceGenderTags,
  updateVoice,
  voiceSamplePath,
  type AudioSummary,
  type ResourceVisibility,
  type TagTranslation,
  type Voice,
  type VoiceSampleSource,
  type VoiceTag,
} from '@/api/voices'
import { ApiError } from '@/api/errors'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceTagPicker from '@/components/ResourceTagPicker.vue'
import ResourceStatus from '@/components/ResourceStatus.vue'
import TagCreationDialog from '@/components/TagCreationDialog.vue'
import VoiceTagLines from '@/components/VoiceTagLines.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { locale, t } = useI18n()
const voice = ref<Voice | null>(null)
const loading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const editing = ref(false)
const confirmDelete = ref(false)
const errorMessage = ref('')
const formError = ref('')
const title = ref('')
const visibility = ref<ResourceVisibility>('private')
const sampleSource = ref<VoiceSampleSource>('original')
const sampleAudioId = ref('')
const sampleAudio = ref<AudioSummary[]>([])
const genderTags = ref<VoiceTag[]>([])
const selectedGenderTagIds = ref<number[]>([])
const editingOptionsLoading = ref(false)
const creatingGenderTag = ref(false)
const tagDialogOpen = ref(false)
const tagDialogInitialEnglishValue = ref('')
const tagDialogError = ref('')
const sampleRevision = ref(0)

const voiceId = computed(() => Number(route.params.id))
const isOwner = computed(
  () =>
    voice.value !== null &&
    voice.value.author.userId.toLowerCase() === auth.user?.userId?.toLowerCase(),
)
const canUse = computed(
  () =>
    voice.value?.status === 'ready' &&
    (isOwner.value || voice.value.visibility === 'public'),
)
const canPlaySample = computed(
  () => isOwner.value || (voice.value?.status === 'ready' && voice.value.visibility === 'public'),
)

function resetForm(current: Voice): void {
  title.value = current.title
  visibility.value = current.visibility
  sampleSource.value = current.sampleSource
  sampleAudioId.value = current.sampleAudioId ? String(current.sampleAudioId) : ''
  selectedGenderTagIds.value = current.tags
    .filter((tag) => tag.type === 'gender')
    .map((tag) => tag.id)
}

async function loadVoice(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  editing.value = false
  try {
    if (!Number.isInteger(voiceId.value) || voiceId.value < 1) {
      throw new TypeError('Voice not found')
    }
    voice.value = await getVoice(voiceId.value, locale.value)
    resetForm(voice.value)
  } catch (error) {
    voice.value = null
    errorMessage.value = error instanceof ApiError ? error.message : t('Voice not found')
  } finally {
    loading.value = false
  }
}

async function beginEditing(): Promise<void> {
  if (!voice.value) return
  resetForm(voice.value)
  formError.value = ''
  editing.value = true
  editingOptionsLoading.value = true
  try {
    const [audioOptions, tagOptions] = await Promise.all([
      listPublicSampleAudio(locale.value),
      listVoiceGenderTags(locale.value),
    ])
    sampleAudio.value = audioOptions
    genderTags.value = tagOptions
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Editing options could not be loaded')
  } finally {
    editingOptionsLoading.value = false
  }
}

function selectGenderTag(tagId: number): void {
  if (!selectedGenderTagIds.value.includes(tagId)) {
    selectedGenderTagIds.value = [...selectedGenderTagIds.value, tagId]
  }
}

function removeGenderTag(tagId: number): void {
  selectedGenderTagIds.value = selectedGenderTagIds.value.filter((id) => id !== tagId)
}

function openTagDialog(query: string): void {
  tagDialogOpen.value = true
  tagDialogInitialEnglishValue.value = query
  tagDialogError.value = ''
}

function closeTagDialog(): void {
  if (creatingGenderTag.value) return
  tagDialogOpen.value = false
  tagDialogInitialEnglishValue.value = ''
  tagDialogError.value = ''
}

async function createAndAddGenderTag(input: {
  englishValue: string
  translations: TagTranslation[]
}): Promise<void> {
  if (creatingGenderTag.value) return
  creatingGenderTag.value = true
  tagDialogError.value = ''
  try {
    const tag = await createVoiceGenderTag(input.englishValue, input.translations)
    genderTags.value = [...genderTags.value, tag]
    selectGenderTag(tag.id)
    tagDialogOpen.value = false
    tagDialogInitialEnglishValue.value = ''
  } catch (error) {
    tagDialogError.value =
      error instanceof ApiError ? error.message : t('Tag could not be created')
  } finally {
    creatingGenderTag.value = false
  }
}

async function saveVoice(): Promise<void> {
  if (!voice.value) return
  formError.value = ''
  saving.value = true
  try {
    const selectedAudioId = Number(sampleAudioId.value)
    voice.value = await updateVoice(voice.value.id, {
      title: title.value,
      visibility: visibility.value,
      genderTagIds: selectedGenderTagIds.value,
      sampleSource: sampleSource.value,
      sampleAudioId:
        sampleSource.value === 'public_audio' && Number.isInteger(selectedAudioId)
          ? selectedAudioId
          : undefined,
    })
    editing.value = false
    sampleRevision.value += 1
    resetForm(voice.value)
  } catch (error) {
    formError.value = error instanceof ApiError ? error.message : t('Voice could not be saved')
  } finally {
    saving.value = false
  }
}

function openDeleteDialog(): void {
  confirmDelete.value = true
}

function closeDeleteDialog(): void {
  if (deleting.value) return
  confirmDelete.value = false
}

async function removeVoice(): Promise<void> {
  if (!voice.value) return
  deleting.value = true
  formError.value = ''
  try {
    await deleteVoice(voice.value.id)
    await router.push({ name: 'voices' })
  } catch (error) {
    confirmDelete.value = false
    formError.value = error instanceof ApiError ? error.message : t('Voice could not be deleted')
  } finally {
    deleting.value = false
  }
}

watch(() => route.params.id, loadVoice, { immediate: true })
</script>

<template>
  <section aria-labelledby="voice-title">
    <p v-if="loading" class="border-b border-line py-12 text-sm text-muted">{{ t('Loading voice') }}</p>
    <div v-else-if="errorMessage && !voice" class="border-b border-line py-12">
      <p role="alert" class="text-sm text-danger">{{ errorMessage }}</p>
      <RouterLink to="/voices" class="mt-4 inline-block text-sm font-medium text-accent underline">
        {{ t('Back to voices') }}
      </RouterLink>
    </div>

    <template v-else-if="voice">
      <div class="flex min-w-0 flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
        <div class="min-w-0">
          <RouterLink to="/voices" class="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Voices') }}
          </RouterLink>
          <h1 id="voice-title" class="break-words text-2xl font-semibold">{{ voice.title }}</h1>
          <RouterLink
            :to="`/user/${voice.author.userId}`"
            class="mt-1 inline-block break-words text-sm text-muted hover:text-ink"
          >
            {{ voice.author.username || voice.author.userId }}
          </RouterLink>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-if="isOwner && !editing"
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
          <RouterLink
            v-if="canUse"
            :to="{ name: 'create', query: { voice: voice.id } }"
            class="inline-flex h-9 items-center gap-2 bg-ink px-3 text-sm font-medium text-white hover:bg-accent"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Use voice') }}
          </RouterLink>
        </div>
      </div>

      <p v-if="formError && !editing" role="alert" class="border-b border-line py-4 text-sm text-danger">
        {{ formError }}
      </p>

      <form v-if="editing" class="border-b border-line bg-surface py-6" @submit.prevent="saveVoice">
        <div class="grid gap-5 md:grid-cols-2">
          <div class="md:col-span-2">
            <label for="voice-title-input" class="mb-1 block text-sm font-medium">{{ t('Title') }}</label>
            <input
              id="voice-title-input"
              v-model="title"
              required
              maxlength="200"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            />
          </div>
          <div>
            <label for="voice-visibility" class="mb-1 block text-sm font-medium">{{ t('Visibility') }}</label>
            <select
              id="voice-visibility"
              v-model="visibility"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            >
              <option value="private">{{ t('Private') }}</option>
              <option value="public" :disabled="voice.status !== 'ready'">{{ t('Public') }}</option>
            </select>
          </div>
          <div>
            <label for="sample-source" class="mb-1 block text-sm font-medium">{{ t('Sample source') }}</label>
            <select
              id="sample-source"
              v-model="sampleSource"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            >
              <option value="original">{{ t('Original recording') }}</option>
              <option value="public_audio">{{ t('Public audio') }}</option>
            </select>
          </div>
          <div v-if="sampleSource === 'public_audio'" class="md:col-span-2">
            <label for="sample-audio" class="mb-1 block text-sm font-medium">{{ t('Public audio') }}</label>
            <select
              id="sample-audio"
              v-model="sampleAudioId"
              required
              :disabled="editingOptionsLoading"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus disabled:bg-canvas"
            >
              <option value="" disabled>{{ editingOptionsLoading ? t('Loading audio') : t('Select audio') }}</option>
              <option v-for="audio in sampleAudio" :key="audio.id" :value="String(audio.id)">
                {{ audio.title }} - {{ audio.author.username || audio.author.userId }}
              </option>
            </select>
          </div>
          <ResourceTagPicker
            class="md:col-span-2"
            label="Gender tags"
            type="gender"
            :tags="genderTags"
            :selected-ids="selectedGenderTagIds"
            @select="selectGenderTag"
            @remove="removeGenderTag"
            @create="openTagDialog"
          />
        </div>
        <p v-if="formError" role="alert" class="mt-4 text-sm text-danger">{{ formError }}</p>
        <div class="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
          <button
            type="button"
            class="inline-flex h-9 items-center gap-2 text-sm font-medium text-danger hover:underline"
            @click="openDeleteDialog"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ t('Delete voice') }}
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
              :disabled="saving || editingOptionsLoading"
              class="h-9 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              {{ saving ? t('Saving') : t('Save') }}
            </button>
          </div>
        </div>
      </form>

      <div class="grid border-b border-line bg-surface md:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="min-w-0 border-b border-line px-4 py-6 md:border-b-0 md:border-r md:px-5">
          <h2 class="text-sm font-semibold">{{ t('Sample') }}</h2>
          <p class="mt-1 text-sm text-muted">
            {{ voice.sampleSource === 'original' ? t('Original recording') : t('Public audio') }}
          </p>
          <audio
            v-if="canPlaySample"
            :key="sampleRevision"
            class="mt-4 h-10 w-full max-w-xl"
            controls
            preload="metadata"
            :src="voiceSamplePath(voice.id)"
          ></audio>
          <p v-else class="mt-4 text-sm text-muted">{{ t('Sample unavailable') }}</p>
        </div>
        <dl class="px-4 py-5 md:px-5">
          <dt class="text-sm text-muted">{{ t('Status') }}</dt>
          <dd class="mt-2"><ResourceStatus :status="voice.status" /></dd>
        </dl>
      </div>

      <div class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]">
        <h2 class="text-sm font-semibold">{{ t('Tags') }}</h2>
        <VoiceTagLines :tags="voice.tags" search-path="/voices" />
      </div>

      <div v-if="isOwner && voice.errorSummary" class="border-b border-line py-6">
        <h2 class="text-sm font-semibold text-danger">{{ t('Generation error') }}</h2>
        <p class="mt-2 break-words text-sm text-muted">{{ voice.errorSummary }}</p>
      </div>
    </template>

    <ConfirmDialog
      :open="confirmDelete"
      :title="t('Delete voice')"
      :busy="deleting"
      confirm-label="Delete"
      @close="closeDeleteDialog"
      @confirm="removeVoice"
    >
      <p>{{ t('This voice and its stored files will be removed.') }}</p>
    </ConfirmDialog>

    <TagCreationDialog
      :open="tagDialogOpen"
      type="gender"
      :initial-english-value="tagDialogInitialEnglishValue"
      :busy="creatingGenderTag"
      :error-message="tagDialogError"
      @close="closeTagDialog"
      @submit="createAndAddGenderTag"
    />
  </section>
</template>
