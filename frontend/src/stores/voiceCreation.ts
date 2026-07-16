import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { cancelJob, getJob, type Job } from '@/api/jobs'
import { createVoiceUpload, type VoiceUploadInput } from '@/api/voices'
import { ApiError } from '@/api/errors'

const STORAGE_KEY = 'listening.voiceCreation'
const POLL_INTERVAL_MS = 1000

interface PersistedCreation {
  jobId: number
  voiceId: number
}

export const useVoiceCreationStore = defineStore('voiceCreation', () => {
  const job = ref<Job | null>(null)
  const jobId = ref<number | null>(null)
  const voiceId = ref<number | null>(null)
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
    if (jobId.value === null || voiceId.value === null) return
    const value: PersistedCreation = {
      jobId: jobId.value,
      voiceId: voiceId.value,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  }

  function restore(): void {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    try {
      const value = JSON.parse(raw) as Partial<PersistedCreation>
      if (
        Number.isInteger(value.jobId) &&
        Number(value.jobId) > 0 &&
        Number.isInteger(value.voiceId) &&
        Number(value.voiceId) > 0
      ) {
        jobId.value = Number(value.jobId)
        voiceId.value = Number(value.voiceId)
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
      if (job.value.result?.type === 'voice') {
        voiceId.value = job.value.result.id
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

  async function submit(input: VoiceUploadInput): Promise<void> {
    if (submitting.value || active.value) return
    stopPolling()
    pollingEnabled = true
    submitting.value = true
    errorMessage.value = ''
    job.value = null
    try {
      const accepted = await createVoiceUpload(input)
      jobId.value = accepted.jobId
      voiceId.value = accepted.voiceId
      persist()
      await refresh()
    } catch (error) {
      errorMessage.value =
        error instanceof ApiError ? error.message : 'Voice upload could not be submitted'
    } finally {
      submitting.value = false
    }
  }

  async function cancel(): Promise<void> {
    if (jobId.value === null || !active.value) return
    try {
      job.value = await cancelJob(jobId.value)
      errorMessage.value = ''
      if (!active.value) stopPolling()
    } catch (error) {
      errorMessage.value =
        error instanceof ApiError ? error.message : 'Task could not be cancelled'
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
    voiceId.value = null
    errorMessage.value = ''
  }

  return {
    job,
    jobId,
    voiceId,
    submitting,
    polling,
    errorMessage,
    active,
    completed,
    failed,
    submit,
    cancel,
    resume,
    refresh,
    stopPolling,
    reset,
  }
})
