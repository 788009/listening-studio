<script setup lang="ts">
import type { Voice } from '@/api/voices'
import type { SpeakerDraft } from './dialogueTurnTypes'
import { useI18n } from '@/i18n'

const props = defineProps<{
  modelValue: SpeakerDraft[]
  voices: Voice[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: SpeakerDraft[]]
  remove: [speakerKey: number]
}>()
const { t } = useI18n()

function updateSpeaker(index: number, update: Partial<SpeakerDraft>): void {
  emit(
    'update:modelValue',
    props.modelValue.map((speaker, position) =>
      position === index ? { ...speaker, ...update } : speaker,
    ),
  )
}

function addSpeaker(): void {
  const nextKey = Math.max(0, ...props.modelValue.map((speaker) => speaker.key)) + 1
  emit('update:modelValue', [
    ...props.modelValue,
    {
      key: nextKey,
      name: '',
      voiceId: props.voices[0] ? String(props.voices[0].id) : '',
    },
  ])
}
</script>

<template>
  <section class="min-w-0 border-b border-line" aria-labelledby="speaker-definitions-title">
    <div class="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
      <h2 id="speaker-definitions-title" class="text-base font-semibold">{{ t('Speakers') }}</h2>
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink"
        @click="addSpeaker"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" /></svg>
        {{ t('Add speaker') }}
      </button>
    </div>

    <ol class="divide-y divide-line">
      <li
        v-for="(speaker, index) in modelValue"
        :key="speaker.key"
        class="grid min-w-0 gap-4 px-5 py-5 sm:grid-cols-[minmax(10rem,0.9fr)_minmax(12rem,1fr)_2.5rem] sm:items-end"
      >
        <div class="min-w-0">
          <label :for="`speaker-name-${speaker.key}`" class="mb-1 block text-sm font-medium">{{ t('Speaker name') }}</label>
          <input
            :id="`speaker-name-${speaker.key}`"
            :value="speaker.name"
            required
            maxlength="200"
            class="h-10 w-full min-w-0 border border-line px-3 text-sm"
            @input="updateSpeaker(index, { name: ($event.target as HTMLInputElement).value })"
          />
        </div>
        <div class="min-w-0">
          <label :for="`speaker-voice-${speaker.key}`" class="mb-1 block text-sm font-medium">{{ t('Voice') }}</label>
          <select
            :id="`speaker-voice-${speaker.key}`"
            :value="speaker.voiceId"
            class="h-10 w-full min-w-0 border border-line bg-surface px-3 text-sm"
            @change="updateSpeaker(index, { voiceId: ($event.target as HTMLSelectElement).value })"
          >
            <option v-for="voice in voices" :key="voice.id" :value="String(voice.id)">{{ voice.title }}</option>
          </select>
        </div>
        <button
          type="button"
          class="flex h-10 w-10 items-center justify-center border border-line text-muted hover:border-danger hover:text-danger disabled:opacity-30"
          :disabled="modelValue.length === 1"
          :title="t('Remove speaker')"
          :aria-label="t('Remove {speaker}', { speaker: speaker.name || t('Speaker {position}', { position: index + 1 }) })"
          @click="emit('remove', speaker.key)"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" stroke="currentColor" stroke-width="2" /></svg>
        </button>
      </li>
    </ol>
  </section>
</template>
