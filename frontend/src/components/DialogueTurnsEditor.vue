<script setup lang="ts">
import type { DialogueTurnDraft, SpeakerDraft } from './dialogueTurnTypes'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const props = defineProps<{
  modelValue: DialogueTurnDraft[]
  speakers: SpeakerDraft[]
  multiple: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: DialogueTurnDraft[]]
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
  emit(
    'update:modelValue',
    props.modelValue.filter((_, position) => position !== index),
  )
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
        class="grid min-w-0 gap-4 px-5 py-5"
        :class="multiple ? 'lg:grid-cols-[4.5rem_minmax(10rem,0.7fr)_minmax(14rem,1.5fr)]' : 'md:grid-cols-[14rem_minmax(14rem,1fr)]'"
      >
        <div v-if="multiple" class="grid h-9 grid-cols-3" :aria-label="t('Turn controls')">
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
      </li>
    </ol>
    <button v-if="multiple" type="button" class="m-5 inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink" @click="addTurn">
      <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" /></svg>
      {{ t('Add turn') }}
    </button>
  </section>
</template>
