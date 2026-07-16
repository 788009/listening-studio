<script setup lang="ts">
import type { PaperSelection } from './paperSelectionTypes'

defineProps<{
  items: PaperSelection[]
  disabled?: boolean
}>()
const emit = defineEmits<{
  move: [index: number, offset: -1 | 1]
  remove: [index: number]
}>()

function duration(seconds: number | null): string {
  if (seconds === null) return ''
  const rounded = Math.max(0, Math.round(seconds))
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}
</script>

<template>
  <ol class="divide-y divide-line border-y border-line bg-surface">
    <li
      v-for="(item, index) in items"
      :key="item.audio.id"
      class="grid min-w-0 grid-cols-[2rem_minmax(0,1fr)_5.5rem] items-center gap-3 px-3 py-4 sm:grid-cols-[2rem_minmax(0,1fr)_7rem] sm:px-4"
    >
      <span class="text-sm tabular-nums text-muted">{{ index + 1 }}</span>
      <div class="min-w-0">
        <div class="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <p class="min-w-0 break-words text-sm font-semibold">{{ item.audio.title }}</p>
          <span v-if="item.audio.durationSeconds !== null" class="text-xs text-muted">
            {{ duration(item.audio.durationSeconds) }}
          </span>
        </div>
        <p class="mt-1 break-words text-xs text-muted">
          {{ item.audio.author.username || item.audio.author.userId }}
        </p>
        <p
          v-if="item.state !== 'valid'"
          class="mt-2 break-words text-xs"
          :class="item.state === 'checking' ? 'text-muted' : 'text-danger'"
          role="status"
        >
          {{ item.message }}
        </p>
      </div>
      <div class="grid h-9 grid-cols-3 justify-self-end" aria-label="Selected audio controls">
        <button
          type="button"
          class="flex h-9 w-7 items-center justify-center text-muted hover:text-ink disabled:opacity-30"
          :disabled="disabled || index === 0"
          :aria-label="`Move ${item.audio.title} up`"
          title="Move up"
          @click="emit('move', index, -1)"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="m6 15 6-6 6 6" stroke="currentColor" stroke-width="2" />
          </svg>
        </button>
        <button
          type="button"
          class="flex h-9 w-7 items-center justify-center text-muted hover:text-ink disabled:opacity-30"
          :disabled="disabled || index === items.length - 1"
          :aria-label="`Move ${item.audio.title} down`"
          title="Move down"
          @click="emit('move', index, 1)"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" />
          </svg>
        </button>
        <button
          type="button"
          class="flex h-9 w-7 items-center justify-center text-muted hover:text-danger disabled:opacity-30"
          :disabled="disabled"
          :aria-label="`Remove ${item.audio.title}`"
          title="Remove"
          @click="emit('remove', index)"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="M5 12h14" stroke="currentColor" stroke-width="2" />
          </svg>
        </button>
      </div>
    </li>
  </ol>
</template>
