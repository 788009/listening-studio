<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import {
  audioMediaPath,
  deleteAudio,
  getAudio,
  updateAudio,
  type Audio,
  type ResourceVisibility,
} from '@/api/audios'
import { ApiError } from '@/api/errors'
import AudioTagLines from '@/components/AudioTagLines.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ResourceStatus from '@/components/ResourceStatus.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
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

const audioId = computed(() => Number(route.params.id))
const locale = computed(() => auth.user?.locale ?? 'en')
const isOwner = computed(
  () =>
    audio.value !== null &&
    audio.value.author.userId.toLowerCase() === auth.user?.userId?.toLowerCase(),
)
const orderedUtterances = computed(() =>
  [...(audio.value?.utterances ?? [])].sort((left, right) => left.position - right.position),
)

function resetForm(current: Audio): void {
  title.value = current.title
  visibility.value = current.visibility
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
    errorMessage.value = error instanceof ApiError ? error.message : 'Audio not found'
  } finally {
    loading.value = false
  }
}

function beginEditing(): void {
  if (!audio.value) return
  resetForm(audio.value)
  formError.value = ''
  editing.value = true
}

async function saveAudio(): Promise<void> {
  if (!audio.value) return
  saving.value = true
  formError.value = ''
  try {
    audio.value = await updateAudio(audio.value.id, {
      title: title.value,
      visibility: visibility.value,
    })
    editing.value = false
    resetForm(audio.value)
  } catch (error) {
    formError.value = error instanceof ApiError ? error.message : 'Audio could not be saved'
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
    formError.value = error instanceof ApiError ? error.message : 'Audio could not be deleted'
  } finally {
    deleting.value = false
  }
}

watch(() => route.params.id, loadAudio, { immediate: true })
</script>

<template>
  <section aria-labelledby="audio-title">
    <p v-if="loading" class="border-b border-line py-12 text-sm text-muted">Loading audio</p>
    <div v-else-if="errorMessage && !audio" class="border-b border-line py-12">
      <p role="alert" class="text-sm text-danger">{{ errorMessage }}</p>
      <RouterLink to="/" class="mt-4 inline-block text-sm font-medium text-accent underline">
        Back to library
      </RouterLink>
    </div>

    <template v-else-if="audio">
      <div class="flex min-w-0 flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
        <div class="min-w-0">
          <RouterLink to="/" class="mb-2 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" />
            </svg>
            Library
          </RouterLink>
          <h1 id="audio-title" class="break-words text-2xl font-semibold">{{ audio.title }}</h1>
          <RouterLink
            :to="`/user/${audio.author.userId}`"
            class="mt-1 inline-block break-words text-sm text-muted hover:text-ink"
          >
            {{ audio.author.username || audio.author.userId }}
          </RouterLink>
        </div>
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
          Edit
        </button>
      </div>

      <p v-if="formError && !editing" role="alert" class="border-b border-line py-4 text-sm text-danger">
        {{ formError }}
      </p>

      <form v-if="editing" class="border-b border-line bg-surface py-6" @submit.prevent="saveAudio">
        <div class="grid gap-5 sm:grid-cols-[minmax(0,1fr)_12rem]">
          <div>
            <label for="audio-title-input" class="mb-1 block text-sm font-medium">Title</label>
            <input
              id="audio-title-input"
              v-model="title"
              required
              maxlength="200"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            />
          </div>
          <div>
            <label for="audio-visibility" class="mb-1 block text-sm font-medium">Visibility</label>
            <select
              id="audio-visibility"
              v-model="visibility"
              class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
            >
              <option value="private">Private</option>
              <option value="public" :disabled="audio.status !== 'ready'">Public</option>
            </select>
          </div>
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
            Delete audio
          </button>
          <div class="flex gap-2">
            <button
              type="button"
              class="h-9 border border-line px-3 text-sm font-medium hover:border-ink"
              @click="editing = false"
            >
              Cancel
            </button>
            <button
              type="submit"
              :disabled="saving"
              class="h-9 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-60"
            >
              {{ saving ? 'Saving' : 'Save' }}
            </button>
          </div>
        </div>
      </form>

      <div class="grid border-b border-line bg-surface md:grid-cols-[minmax(0,1fr)_18rem]">
        <div class="min-w-0 border-b border-line px-4 py-6 md:border-b-0 md:border-r md:px-5">
          <h2 class="text-sm font-semibold">Playback</h2>
          <audio
            v-if="audio.status === 'ready'"
            class="mt-4 h-10 w-full max-w-xl"
            controls
            preload="metadata"
            :src="audioMediaPath(audio.id)"
          ></audio>
          <p v-else class="mt-4 text-sm text-muted">Audio unavailable</p>
        </div>
        <dl class="grid grid-cols-2 md:grid-cols-1">
          <div class="border-r border-line px-4 py-5 md:border-b md:border-r-0 md:px-5">
            <dt class="text-sm text-muted">Status</dt>
            <dd class="mt-2"><ResourceStatus :status="audio.status" /></dd>
          </div>
          <div class="px-4 py-5 md:px-5">
            <dt class="text-sm text-muted">Visibility</dt>
            <dd class="mt-2 text-sm font-medium capitalize">{{ audio.visibility }}</dd>
          </div>
        </dl>
      </div>

      <div class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]">
        <h2 class="text-sm font-semibold">Tags</h2>
        <AudioTagLines :tags="audio.tags" />
      </div>

      <div class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]">
        <h2 class="text-sm font-semibold">Text</h2>
        <p class="min-w-0 whitespace-pre-wrap break-words text-sm leading-6">{{ audio.text }}</p>
      </div>

      <div
        v-if="orderedUtterances.length > 0"
        class="grid gap-6 border-b border-line py-6 md:grid-cols-[10rem_minmax(0,1fr)]"
      >
        <h2 class="text-sm font-semibold">Speakers</h2>
        <ol class="min-w-0 space-y-4">
          <li
            v-for="utterance in orderedUtterances"
            :key="utterance.position"
            class="grid min-w-0 gap-1 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-4"
          >
            <span class="break-words text-sm font-medium">{{ utterance.speakerDisplayName }}</span>
            <p class="min-w-0 break-words text-sm leading-6">{{ utterance.text }}</p>
          </li>
        </ol>
      </div>

      <div v-if="isOwner && audio.errorSummary" class="border-b border-line py-6">
        <h2 class="text-sm font-semibold text-danger">Generation error</h2>
        <p class="mt-2 break-words text-sm text-muted">{{ audio.errorSummary }}</p>
      </div>
    </template>

    <ConfirmDialog
      :open="confirmDelete"
      title="Delete audio"
      :busy="deleting"
      confirm-label="Delete"
      @close="confirmDelete = false"
      @confirm="removeAudio"
    >
      <p>This audio and its stored file will be removed.</p>
    </ConfirmDialog>
  </section>
</template>
