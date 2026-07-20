<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onBeforeRouteLeave, RouterLink } from 'vue-router'

import {
  createVoiceGenderTag,
  listVoiceGenderTags,
  type ResourceVisibility,
  type VoiceTag,
} from '@/api/voices'
import { ApiError } from '@/api/errors'
import ActiveJobProgress from '@/components/ActiveJobProgress.vue'
import { useVoiceCreationStore } from '@/stores/voiceCreation'
import { useI18n } from '@/i18n'

const { locale, t } = useI18n()
const creation = useVoiceCreationStore()
const title = ref('')
const file = ref<File | null>(null)
const genderTagId = ref('')
const visibility = ref<ResourceVisibility>('public')
const genderTags = ref<VoiceTag[]>([])
const newGenderTag = ref('')
const tagsLoading = ref(true)
const tagCreating = ref(false)
const formError = ref('')

const progressStages = computed(() => [
  { threshold: 5, label: t('Preparing reference audio') },
  { threshold: 20, label: t('Generating voice model') },
  { threshold: 80, label: t('Saving voice model') },
  { threshold: 90, label: t('Finalizing voice') },
])
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
    formError.value = t('Choose a reference recording')
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
  visibility.value = 'public'
  formError.value = ''
}

onMounted(() => {
  creation.resume()
  void loadGenderTags()
})
onBeforeRouteLeave(() => {
  if (creation.completed || creation.failed) {
    creation.reset()
  } else {
    creation.stopPolling()
  }
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
      <ActiveJobProgress
        :progress="creation.job?.progress ?? 0"
        :queued="creation.job?.status === 'queued'"
        :queued-label="t('Waiting for processing')"
        :stages="progressStages"
        :task-label="t('Task {id}', { id: creation.jobId ?? '' })"
        :progress-label="t('Voice creation progress')"
      />
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
          <label for="voice-file" class="mb-1 block text-sm font-medium">{{ t('Reference audio') }}</label>
          <input
            id="voice-file"
            type="file"
            required
            accept=".wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm"
            class="block w-full border border-line bg-surface text-sm text-muted file:mr-4 file:h-10 file:border-0 file:border-r file:border-line file:bg-canvas file:px-3 file:text-sm file:font-medium file:text-ink hover:file:bg-accent-soft"
            @change="selectFile"
          />
        </div>

        <fieldset>
          <legend class="mb-2 text-sm font-medium">{{ t('Gender tag') }}</legend>
          <div class="flex min-w-0 flex-wrap gap-2" :aria-busy="tagsLoading">
            <label
              class="tag-chip tag-chip-interactive cursor-pointer"
              :class="{ 'tag-chip-selected': genderTagId === '', 'opacity-50': tagsLoading }"
            >
              <input v-model="genderTagId" type="radio" value="" class="sr-only" :disabled="tagsLoading" />
              {{ t('No gender tag') }}
            </label>
            <label
              v-for="tag in genderTags"
              :key="tag.id"
              class="tag-chip tag-chip-interactive cursor-pointer"
              :class="{ 'tag-chip-selected': genderTagId === String(tag.id), 'opacity-50': tagsLoading }"
            >
              <input v-model="genderTagId" type="radio" :value="String(tag.id)" class="sr-only" :disabled="tagsLoading" />
              {{ tag.displayValue.replace(/_/g, ' ') }}
            </label>
          </div>
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
        </fieldset>
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
