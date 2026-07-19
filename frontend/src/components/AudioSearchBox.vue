<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  autocompleteAudioTags,
  type AudioTag,
} from '@/api/audios'
import { useI18n } from '@/i18n'

const { t } = useI18n()

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
let suggestionRequest = 0
let pendingUserValue: string | undefined

function tokenFor(value: string): string {
  const tokens = value.trimStart().split(/\s+/)
  return tokens[tokens.length - 1] ?? ''
}

const currentToken = computed(() => tokenFor(props.modelValue))

function displayValue(value: string): string {
  const tag = props.tags.find((item) => item.fullTag === value)
  if (!tag) return value.replace(/_/g, ' ')
  const type = t(tag.type.charAt(0).toUpperCase() + tag.type.slice(1))
  return `${type}: ${tag.displayValue.replace(/_/g, ' ')}`
}

async function loadSuggestions(inputValue: string): Promise<void> {
  const token = tokenFor(inputValue)
  const request = ++suggestionRequest
  if (!token) {
    suggestions.value = []
    open.value = false
    return
  }
  try {
    const results = await autocompleteAudioTags(token)
    if (request !== suggestionRequest || inputValue !== props.modelValue) return
    const existingTerms = new Set(
      inputValue
        .trim()
        .split(/\s+/)
        .slice(0, -1)
        .map((term) => term.normalize('NFKC').toLocaleLowerCase()),
    )
    suggestions.value = results.filter(
      (suggestion) => !existingTerms.has(suggestion.normalize('NFKC').toLocaleLowerCase()),
    )
    activeIndex.value = -1
    open.value = suggestions.value.length > 0
  } catch {
    if (request !== suggestionRequest) return
    suggestions.value = []
    open.value = false
  }
}

function clearSuggestions(): void {
  clearTimeout(debounceTimer)
  suggestionRequest += 1
  suggestions.value = []
  activeIndex.value = -1
  open.value = false
}

function handleInput(event: Event): void {
  const value = (event.target as HTMLInputElement).value
  pendingUserValue = value
  emit('update:modelValue', value)
  clearSuggestions()
  if (tokenFor(value)) {
    debounceTimer = setTimeout(() => loadSuggestions(value), 150)
  }
}

watch(
  () => props.modelValue,
  (value) => {
    if (value === pendingUserValue) {
      pendingUserValue = undefined
      return
    }
    pendingUserValue = undefined
    clearSuggestions()
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
  clearSuggestions()
  emit('submit')
}

function closeLater(): void {
  setTimeout(() => {
    open.value = false
  }, 120)
}

onBeforeUnmount(() => {
  clearTimeout(debounceTimer)
  suggestionRequest += 1
})
</script>

<template>
  <form class="flex flex-col gap-3 sm:flex-row sm:items-end" role="search" @submit.prevent="submit">
    <div class="relative min-w-0 flex-1">
      <label for="audio-search" class="mb-1 block text-sm font-medium">{{ t('Search audio') }}</label>
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
        @input="handleInput"
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
      {{ t('Search') }}
    </button>
  </form>
</template>
