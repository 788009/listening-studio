<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  createVoiceGenderTag,
  listVoiceGenderTags,
  type ResourceVisibility,
  type VoiceTag,
} from '@/api/voices'
import { ApiError } from '@/api/errors'
import { useVoiceCreationStore } from '@/stores/voiceCreation'
import { useI18n } from '@/i18n'

const { locale, t } = useI18n()
const creation = useVoiceCreationStore()
const title = ref('')
const file = ref<File | null>(null)
const genderTagId = ref('')
const visibility = ref<ResourceVisibility>('private')
const genderTags = ref<VoiceTag[]>([])
const newGenderTag = ref('')
const tagsLoading = ref(true)
const tagCreating = ref(false)
const formError = ref('')

const statusLabel = computed(() => {
  if (creation.job?.status === 'running') return t('Generating voice model')
  if (creation.job?.status === 'queued') return t('Waiting for processing')
  return ''
})
const failureMessage = computed(
  () => creation.job?.errorSummary || creation.errorMessage,
)

async function loadGenderTags(): Promise<void> {
  tagsLoading.value = true
  try {
    genderTags.value = await listVoiceGenderTags(locale.value)
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Gender tags could not be loaded')
  } finally {
    tagsLoading.value = false
  }
}

async function addGenderTag(): Promise<void> {
  const value = newGenderTag.value.trim()
  if (!value || tagCreating.value) return
  tagCreating.value = true
  formError.value = ''
  try {
    const tag = await createVoiceGenderTag(value)
    genderTags.value = [...genderTags.value, tag]
    genderTagId.value = String(tag.id)
    newGenderTag.value = ''
  } catch (error) {
    formError.value =
      error instanceof ApiError ? error.message : t('Tag could not be created')
  } finally {
    tagCreating.value = false
  }
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

async function submit(): Promise<void> {
  formError.value = ''
  const normalizedTitle = title.value.trim()
  if (!normalizedTitle) {
    formError.value = t('Enter a title')
    return
  }
  if (!file.value) {
    formError.value = t('Choose a WAV reference recording')
    return
  }
  const selectedGenderId = Number(genderTagId.value)
  await creation.submit({
    title: normalizedTitle,
    file: file.value,
    visibility: visibility.value,
    genderTagId:
      genderTagId.value && Number.isInteger(selectedGenderId)
        ? selectedGenderId
        : undefined,
  })
}

function startAnother(): void {
  creation.reset()
  title.value = ''
  file.value = null
  genderTagId.value = ''
  newGenderTag.value = ''
  visibility.value = 'private'
  formError.value = ''
}

onMounted(() => {
  creation.resume()
  void loadGenderTags()
})
onUnmounted(creation.stopPolling)
</script>

<template>
  <section class="page-shell" aria-labelledby="create-title">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ t('Teacher workspace') }}</p>
        <h1 id="create-title" class="text-3xl font-semibold">{{ t('Create voice') }}</h1>
      </div>
    </div>

    <div v-if="creation.active" class="mt-6 rounded-lg border border-line bg-surface px-5 py-8 shadow-panel">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-base font-semibold">{{ statusLabel }}</p>
          <p class="mt-1 text-sm text-muted">{{ t('Task {id}', { id: creation.jobId ?? '' }) }}</p>
        </div>
        <span class="text-sm font-medium tabular-nums">{{ creation.job?.progress ?? 0 }}%</span>
      </div>
      <div
        class="mt-5 h-2 overflow-hidden bg-canvas"
        role="progressbar"
        :aria-label="t('Voice creation progress')"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="creation.job?.progress ?? 0"
      >
        <div
          class="h-full bg-accent transition-[width] motion-reduce:transition-none"
          :style="{ width: `${creation.job?.progress ?? 0}%` }"
        />
      </div>
    </div>

    <div v-else-if="creation.completed && creation.voiceId" class="mt-6 rounded-lg border border-line bg-surface px-5 py-9 shadow-panel">
      <p class="text-base font-semibold text-success">{{ t('Voice is ready') }}</p>
      <div class="mt-5 flex flex-wrap gap-3">
        <RouterLink
          :to="`/voice/${creation.voiceId}`"
          class="inline-flex h-10 items-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent"
        >
          {{ t('View voice') }}
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
          </svg>
        </RouterLink>
        <button
          type="button"
          class="h-10 border border-line bg-surface px-4 text-sm font-medium hover:border-ink"
          @click="startAnother"
        >
          {{ t('Create another') }}
        </button>
      </div>
    </div>

    <div v-else-if="creation.failed" class="mt-6 rounded-lg border border-danger/30 bg-surface px-5 py-9 shadow-panel">
      <p class="text-base font-semibold">{{ t('Voice creation failed') }}</p>
      <p role="alert" class="mt-2 text-sm text-danger">
        {{ failureMessage || t('The task could not be completed') }}
      </p>
      <button
        type="button"
        class="mt-5 h-10 border border-line bg-surface px-4 text-sm font-medium hover:border-ink"
        @click="startAnother"
      >
        {{ t('Try again') }}
      </button>
    </div>

    <form
      v-else
      class="mt-6 grid overflow-hidden rounded-lg border border-line bg-surface shadow-panel lg:grid-cols-[minmax(0,1fr)_18rem]"
      @submit.prevent="submit"
    >
      <div class="space-y-5 px-5 py-7 lg:border-r lg:border-line">
        <div>
          <label for="voice-title" class="mb-1 block text-sm font-medium">{{ t('Title') }}</label>
          <input
            id="voice-title"
            v-model="title"
            type="text"
            required
            maxlength="200"
            autocomplete="off"
            class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>

        <div>
          <label for="voice-file" class="mb-1 block text-sm font-medium">{{ t('Reference WAV') }}</label>
          <input
            id="voice-file"
            type="file"
            required
            accept=".wav,audio/wav,audio/x-wav"
            class="block w-full border border-line bg-surface text-sm text-muted file:mr-4 file:h-10 file:border-0 file:border-r file:border-line file:bg-canvas file:px-3 file:text-sm file:font-medium file:text-ink hover:file:bg-accent-soft"
            @change="selectFile"
          />
        </div>

        <div>
          <label for="voice-gender" class="mb-1 block text-sm font-medium">{{ t('Gender tag') }}</label>
          <select
            id="voice-gender"
            v-model="genderTagId"
            :disabled="tagsLoading"
            class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus disabled:text-muted"
          >
            <option value="">{{ t('No gender tag') }}</option>
            <option v-for="tag in genderTags" :key="tag.id" :value="String(tag.id)">
              {{ tag.displayValue.replace(/_/g, ' ') }}
            </option>
          </select>
          <div class="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <label for="voice-new-gender" class="sr-only">{{ t('New gender tag') }}</label>
            <input
              id="voice-new-gender"
              v-model="newGenderTag"
              type="text"
              maxlength="255"
              :placeholder="t('New gender tag')"
              class="h-9 min-w-0 border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
              @keydown.enter.prevent="addGenderTag"
            />
            <button
              type="button"
              :disabled="tagCreating || !newGenderTag.trim()"
              class="h-9 border border-line bg-surface px-3 text-sm font-medium hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
              @click="addGenderTag"
            >
              {{ t('Add tag') }}
            </button>
          </div>
        </div>
      </div>

      <div class="flex flex-col justify-between gap-7 px-5 py-7">
        <label class="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            class="mt-0.5 h-4 w-4 accent-accent"
            :checked="visibility === 'public'"
            @change="visibility = ($event.target as HTMLInputElement).checked ? 'public' : 'private'"
          />
          <span>
            <span class="block text-sm font-medium">{{ t('Publish when ready') }}</span>
            <span class="mt-1 block text-sm text-muted">{{ t('Private voices remain visible only to you.') }}</span>
          </span>
        </label>

        <div>
          <p v-if="formError || creation.errorMessage" role="alert" class="mb-3 text-sm text-danger">
            {{ formError || creation.errorMessage }}
          </p>
          <button
            type="submit"
            :disabled="creation.submitting || creation.active"
            class="inline-flex h-10 w-full items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M12 16V4m0 0L7 9m5-5 5 5" stroke="currentColor" stroke-width="2" />
              <path d="M5 14v6h14v-6" stroke="currentColor" stroke-width="2" />
            </svg>
            {{ creation.submitting ? t('Submitting') : t('Create voice') }}
          </button>
        </div>
      </div>
    </form>
  </section>
</template>
