<script setup lang="ts">
import type {
  DialogueTurnDraft,
  DialogueTurnPreview,
  SpeakerDraft,
} from './dialogueTurnTypes'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const props = defineProps<{
  modelValue: DialogueTurnDraft[]
  speakers: SpeakerDraft[]
  previews: Record<number, DialogueTurnPreview>
  canUpload: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: DialogueTurnDraft[]]
  generate: [turnKey: number]
  regenerateSegment: [turnKey: number, segmentPosition: number]
  upload: [turnKey: number, file: File]
  remove: [turnKey: number]
}>()

function updateTurn(index: number, update: Partial<DialogueTurnDraft>): void {
  emit(
    'update:modelValue',
    props.modelValue.map((turn, position) =>
      position === index ? { ...turn, ...update } : turn,
    ),
  )
}

function addTurn(): void {
  const nextKey = Math.max(0, ...props.modelValue.map((turn) => turn.key)) + 1
  emit('update:modelValue', [
    ...props.modelValue,
    {
      key: nextKey,
      speakerKey: props.speakers[0]?.key ?? '',
      text: '',
    },
  ])
}

function removeTurn(index: number): void {
  if (props.modelValue.length <= 1) return
  const turn = props.modelValue[index]
  if (turn) emit('remove', turn.key)
  emit(
    'update:modelValue',
    props.modelValue.filter((_, position) => position !== index),
  )
}

function preview(turnKey: number): DialogueTurnPreview {
  return props.previews[turnKey] ?? { status: 'idle', progress: 0, segments: [] }
}

function segmentBusy(turnKey: number, segmentPosition: number): boolean {
  const segment = preview(turnKey).segments[segmentPosition]
  return Boolean(
    segment && ['submitting', 'queued', 'running'].includes(segment.status),
  )
}

function segmentGenerateLabel(turnKey: number, segmentPosition: number): string {
  const segment = preview(turnKey).segments[segmentPosition]
  if (!segment) return t('Regenerate segment')
  if (segment.status === 'submitting') return t('Submitting')
  if (segment.status === 'queued') return t('Waiting')
  if (segment.status === 'running') {
    return t('Generating {progress}%', { progress: segment.progress })
  }
  return t('Regenerate segment')
}

function isBusy(turnKey: number): boolean {
  return ['submitting', 'queued', 'running'].includes(preview(turnKey).status)
}

function generateLabel(turnKey: number): string {
  const current = preview(turnKey)
  if (current.status === 'submitting') return t('Submitting')
  if (current.status === 'queued') return t('Waiting')
  if (current.status === 'running') {
    return t('Generating {progress}%', { progress: current.progress })
  }
  if (['succeeded', 'failed'].includes(current.status)) {
    return t('Regenerate preview')
  }
  return t('Generate preview')
}

function moveTurn(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= props.modelValue.length) return
  const next = [...props.modelValue]
  const [turn] = next.splice(index, 1)
  if (!turn) return
  next.splice(target, 0, turn)
  emit('update:modelValue', next)
}

function speakerLabel(speaker: SpeakerDraft, index: number): string {
  return speaker.name.trim() || t('Speaker {position}', { position: index + 1 })
}

function selectUpload(turnKey: number, event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) emit('upload', turnKey, file)
}
</script>

<template>
  <section class="min-w-0 border-b border-line" aria-labelledby="listening-content-title">
    <div class="border-b border-line px-5 py-4">
      <h2 id="listening-content-title" class="text-base font-semibold">{{ t('Listening content') }}</h2>
    </div>
    <ol class="min-w-0 divide-y divide-line">
      <li
        v-for="(turn, index) in modelValue"
        :key="turn.key"
        class="min-w-0 px-5 py-5"
      >
        <div class="grid min-w-0 gap-4 lg:grid-cols-[4.5rem_minmax(10rem,0.6fr)_minmax(14rem,1.2fr)_minmax(15rem,0.8fr)]">
          <div class="grid h-9 grid-cols-3" :aria-label="t('Turn controls')">
            <button type="button" class="flex h-9 w-6 items-center justify-center text-muted hover:text-ink disabled:opacity-30" :disabled="index === 0" :title="t('Move turn up')" :aria-label="t('Move turn {position} up', { position: index + 1 })" @click="moveTurn(index, -1)">
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m6 15 6-6 6 6" stroke="currentColor" stroke-width="2" /></svg>
            </button>
            <button type="button" class="flex h-9 w-6 items-center justify-center text-muted hover:text-ink disabled:opacity-30" :disabled="index === modelValue.length - 1" :title="t('Move turn down')" :aria-label="t('Move turn {position} down', { position: index + 1 })" @click="moveTurn(index, 1)">
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" /></svg>
            </button>
            <button type="button" class="flex h-9 w-6 items-center justify-center text-muted hover:text-danger disabled:opacity-30" :disabled="modelValue.length === 1" :title="t('Delete turn')" :aria-label="t('Delete turn {position}', { position: index + 1 })" @click="removeTurn(index)">
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 14h10l1-14" stroke="currentColor" stroke-width="2" /></svg>
            </button>
          </div>
          <div class="min-w-0">
            <label :for="`turn-speaker-${turn.key}`" class="mb-1 block text-sm font-medium">{{ t('Speaker') }}</label>
            <select
              :id="`turn-speaker-${turn.key}`"
              :value="turn.speakerKey"
              required
              class="h-10 w-full min-w-0 border border-line bg-surface px-3 text-sm"
              @change="updateTurn(index, { speakerKey: Number(($event.target as HTMLSelectElement).value) })"
            >
              <option v-for="(speaker, speakerIndex) in speakers" :key="speaker.key" :value="speaker.key">
                {{ speakerLabel(speaker, speakerIndex) }}
              </option>
            </select>
          </div>
          <div class="min-w-0">
            <label :for="`turn-text-${turn.key}`" class="mb-1 block text-sm font-medium">{{ t('Text') }}</label>
            <textarea :id="`turn-text-${turn.key}`" :value="turn.text" required class="min-h-24 w-full min-w-0 resize-y border border-line p-3 text-sm leading-6" @input="updateTurn(index, { text: ($event.target as HTMLTextAreaElement).value })" />
          </div>
          <div class="flex min-w-0 flex-col gap-3 lg:pt-6">
            <p v-if="preview(turn.key).status === 'failed'" role="alert" class="break-words text-xs leading-5 text-danger">
              {{ preview(turn.key).errorMessage || t('Preview generation failed') }}
            </p>
            <p v-else-if="isBusy(turn.key)" class="text-xs leading-5 text-muted">
              {{ t('Generating preview') }}
            </p>
            <button
              type="button"
              class="inline-flex h-9 w-full items-center justify-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="isBusy(turn.key)"
              @click="emit('generate', turn.key)"
            >
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4 shrink-0" aria-hidden="true">
                <path d="M8 5v14l11-7Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" />
              </svg>
              <span class="min-w-0 truncate">{{ generateLabel(turn.key) }}</span>
            </button>
            <label
              v-if="canUpload"
              class="inline-flex h-9 w-full cursor-pointer items-center justify-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
              :class="{ 'pointer-events-none opacity-50': isBusy(turn.key) }"
            >
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4 shrink-0" aria-hidden="true">
                <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <span class="min-w-0 truncate">{{ t('Upload preview audio') }}</span>
              <input
                type="file"
                class="sr-only"
                accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/flac,audio/ogg,audio/webm,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm"
                :disabled="isBusy(turn.key)"
                :aria-label="t('Upload audio for turn {position}', { position: index + 1 })"
                @change="selectUpload(turn.key, $event)"
              />
            </label>
          </div>
        </div>

        <ol
          v-if="preview(turn.key).segments.length"
          class="mt-5 divide-y divide-line border-t border-line lg:ml-[5.5rem]"
          :aria-label="t('Preview segments for turn {position}', { position: index + 1 })"
        >
          <li
            v-for="(segment, segmentIndex) in preview(turn.key).segments"
            :key="`${segmentIndex}-${segment.text}`"
            class="grid min-w-0 gap-3 py-4 md:grid-cols-[2.5rem_minmax(0,1fr)_minmax(12rem,0.55fr)] md:items-center"
          >
            <span class="text-xs font-semibold text-muted">
              {{ t('Segment {position}', { position: segmentIndex + 1 }) }}
            </span>
            <p class="min-w-0 break-words text-sm leading-6">{{ segment.text }}</p>
            <div class="flex min-w-0 flex-col gap-2">
              <audio
                v-if="segment.mediaPath"
                :key="segment.mediaPath"
                :src="segment.mediaPath"
                controls
                preload="metadata"
                class="h-10 w-full min-w-0"
                :aria-label="t('Preview segment {segment} of turn {turn}', { segment: segmentIndex + 1, turn: index + 1 })"
              />
              <p v-if="segment.status === 'failed'" role="alert" class="break-words text-xs leading-5 text-danger">
                {{ segment.errorMessage || t('Preview generation failed') }}
              </p>
              <button
                type="button"
                class="inline-flex h-9 w-full items-center justify-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="segmentBusy(turn.key, segmentIndex) || preview(turn.key).status === 'submitting'"
                @click="emit('regenerateSegment', turn.key, segmentIndex)"
              >
                <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4 shrink-0" aria-hidden="true">
                  <path d="M20 11a8 8 0 1 0-2.34 5.66M20 5v6h-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                <span class="min-w-0 truncate">{{ segmentGenerateLabel(turn.key, segmentIndex) }}</span>
              </button>
            </div>
          </li>
        </ol>
      </li>
    </ol>
    <button type="button" class="m-5 inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink" @click="addTurn">
      <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" /></svg>
      {{ t('Add turn') }}
    </button>
  </section>
</template>
