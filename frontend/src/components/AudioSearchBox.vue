<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  autocompleteAudioTags,
  type AudioTag,
} from '@/api/audios'

const props = defineProps<{
  modelValue: string
  tags: AudioTag[]
  busy?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
}>()
const suggestions = ref<string[]>([])
const open = ref(false)
const activeIndex = ref(-1)
let debounceTimer: ReturnType<typeof setTimeout> | undefined

const currentToken = computed(() => {
  const tokens = props.modelValue.trimStart().split(/\s+/)
  return tokens[tokens.length - 1] ?? ''
})

function displayValue(value: string): string {
  const tag = props.tags.find((item) => item.fullTag === value)
  if (!tag) return value.replace(/_/g, ' ')
  const type = tag.type.charAt(0).toUpperCase() + tag.type.slice(1)
  return `${type}: ${tag.displayValue.replace(/_/g, ' ')}`
}

async function loadSuggestions(): Promise<void> {
  const token = currentToken.value
  if (!token) {
    suggestions.value = []
    open.value = false
    return
  }
  try {
    suggestions.value = await autocompleteAudioTags(token)
    activeIndex.value = -1
    open.value = suggestions.value.length > 0
  } catch {
    suggestions.value = []
    open.value = false
  }
}

watch(
  () => props.modelValue,
  () => {
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(loadSuggestions, 150)
  },
)

function choose(value: string): void {
  const leading = props.modelValue.match(/^\s*/)?.[0] ?? ''
  const trimmed = props.modelValue.trimStart()
  const tokenStart = trimmed.lastIndexOf(currentToken.value)
  const prefix = tokenStart >= 0 ? trimmed.slice(0, tokenStart) : ''
  emit('update:modelValue', `${leading}${prefix}${value} `)
  suggestions.value = []
  open.value = false
}

function handleKeydown(event: KeyboardEvent): void {
  if (!open.value || suggestions.value.length === 0) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % suggestions.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value =
      (activeIndex.value - 1 + suggestions.value.length) % suggestions.value.length
  } else if (event.key === 'Enter' && activeIndex.value >= 0) {
    event.preventDefault()
    choose(suggestions.value[activeIndex.value] ?? '')
  } else if (event.key === 'Escape') {
    open.value = false
  }
}

function submit(): void {
  open.value = false
  emit('submit')
}

function closeLater(): void {
  setTimeout(() => {
    open.value = false
  }, 120)
}

onBeforeUnmount(() => clearTimeout(debounceTimer))
</script>

<template>
  <form class="flex flex-col gap-3 sm:flex-row sm:items-end" role="search" @submit.prevent="submit">
    <div class="relative min-w-0 flex-1">
      <label for="audio-search" class="mb-1 block text-sm font-medium">Search audio</label>
      <input
        id="audio-search"
        :value="modelValue"
        type="search"
        maxlength="1024"
        autocomplete="off"
        role="combobox"
        aria-autocomplete="list"
        :aria-expanded="open"
        aria-controls="audio-search-suggestions"
        :aria-activedescendant="activeIndex >= 0 ? `audio-suggestion-${activeIndex}` : undefined"
        class="h-10 w-full border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @keydown="handleKeydown"
        @focus="suggestions.length > 0 && (open = true)"
        @blur="closeLater"
      />
      <ul
        v-if="open"
        id="audio-search-suggestions"
        role="listbox"
        class="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto border border-line bg-surface shadow-lg"
      >
        <li v-for="(suggestion, index) in suggestions" :key="suggestion" role="presentation">
          <button
            :id="`audio-suggestion-${index}`"
            type="button"
            role="option"
            :aria-selected="index === activeIndex"
            class="block w-full px-3 py-2 text-left text-sm hover:bg-canvas"
            :class="{ 'bg-accent-soft': index === activeIndex }"
            @mousedown.prevent="choose(suggestion)"
          >
            {{ displayValue(suggestion) }}
          </button>
        </li>
      </ul>
    </div>
    <button
      type="submit"
      :disabled="busy"
      class="inline-flex h-10 shrink-0 items-center justify-center gap-2 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-60"
    >
      <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
        <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" />
        <path d="m16 16 4 4" stroke="currentColor" stroke-width="2" />
      </svg>
      Search
    </button>
  </form>
</template>
