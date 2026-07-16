import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createDialogueAudio,
  createSingleAudio,
  type DialogueAudioCreationInput,
  type SingleAudioCreationInput,
} from '@/api/audios'
import { getJob, type Job } from '@/api/jobs'
import { ApiError } from '@/api/errors'

const STORAGE_KEY = 'listening.audioCreation'
const POLL_INTERVAL_MS = 1000

interface PersistedCreation {
  jobId: number
  audioId: number
}

export const useAudioCreationStore = defineStore('audioCreation', () => {
  const job = ref<Job | null>(null)
  const jobId = ref<number | null>(null)
  const audioId = ref<number | null>(null)
  const submitting = ref(false)
  const polling = ref(false)
  const errorMessage = ref('')
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let pollingEnabled = false

  const active = computed(
    () => job.value?.status === 'queued' || job.value?.status === 'running',
  )
  const completed = computed(() => job.value?.status === 'succeeded')
  const failed = computed(
    () => job.value?.status === 'failed' || job.value?.status === 'cancelled',
  )

  function persist(): void {
    if (jobId.value === null || audioId.value === null) return
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ jobId: jobId.value, audioId: audioId.value }),
    )
  }

  function restore(): void {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    try {
      const value = JSON.parse(raw) as Partial<PersistedCreation>
      if (
        Number.isInteger(value.jobId) &&
        Number(value.jobId) > 0 &&
        Number.isInteger(value.audioId) &&
        Number(value.audioId) > 0
      ) {
        jobId.value = Number(value.jobId)
        audioId.value = Number(value.audioId)
      } else {
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch {
      localStorage.removeItem(STORAGE_KEY)
    }
  }

  function schedulePoll(): void {
    if (!pollingEnabled) return
    clearTimeout(pollTimer)
    pollTimer = setTimeout(refresh, POLL_INTERVAL_MS)
  }

  async function refresh(): Promise<void> {
    if (jobId.value === null || polling.value) return
    polling.value = true
    try {
      job.value = await getJob(jobId.value)
      errorMessage.value = ''
      if (job.value.result?.type === 'audio') {
        audioId.value = job.value.result.id
        persist()
      }
      if (active.value) schedulePoll()
    } catch (error) {
      errorMessage.value =
        error instanceof ApiError ? error.message : 'Task status could not be loaded'
      schedulePoll()
    } finally {
      polling.value = false
    }
  }

  async function submitSingle(input: SingleAudioCreationInput): Promise<void> {
    await submit(() => createSingleAudio(input))
  }

  async function submitDialogue(
    input: DialogueAudioCreationInput,
  ): Promise<void> {
    await submit(() => createDialogueAudio(input))
  }

  async function submit(
    create: () => Promise<{ audioId: number; jobId: number }>,
  ): Promise<void> {
    if (submitting.value || active.value) return
    stopPolling()
    pollingEnabled = true
    submitting.value = true
    errorMessage.value = ''
    job.value = null
    try {
      const accepted = await create()
      jobId.value = accepted.jobId
      audioId.value = accepted.audioId
      persist()
      await refresh()
    } catch (error) {
      errorMessage.value =
        error instanceof ApiError ? error.message : 'Audio could not be submitted'
    } finally {
      submitting.value = false
    }
  }

  function resume(): void {
    pollingEnabled = true
    if (jobId.value === null) restore()
    if (jobId.value !== null) void refresh()
  }

  function stopPolling(): void {
    pollingEnabled = false
    clearTimeout(pollTimer)
    pollTimer = undefined
  }

  function reset(): void {
    stopPolling()
    localStorage.removeItem(STORAGE_KEY)
    job.value = null
    jobId.value = null
    audioId.value = null
    errorMessage.value = ''
  }

  return {
    job,
    jobId,
    audioId,
    submitting,
    polling,
    errorMessage,
    active,
    completed,
    failed,
    submitSingle,
    submitDialogue,
    resume,
    refresh,
    stopPolling,
    reset,
  }
})
