<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'

import TagChip from '@/components/TagChip.vue'
import { useI18n } from '@/i18n'

export type EditableTagType = 'gender' | 'topic' | 'category'

interface SelectableTag {
  id: number
  type: string
  englishValue: string
  displayValue: string
  fullTag: string
  translations: { language: string; value: string }[]
}

const props = defineProps<{
  label: string
  type: EditableTagType
  tags: SelectableTag[]
  selectedIds: number[]
  lockedIds?: number[]
}>()
const emit = defineEmits<{
  select: [tagId: number]
  remove: [tagId: number]
  create: [query: string]
}>()
const { t } = useI18n()
const query = ref('')
const activeIndex = ref(-1)
const inputId = useId()
const resultsId = useId()

const typeTags = computed(() => props.tags.filter((tag) => tag.type === props.type))
const selectedTags = computed(() =>
  typeTags.value.filter((tag) => props.selectedIds.includes(tag.id)),
)
const matches = computed(() => {
  const search = normalizeSearchValue(query.value)
  if (!search) return []
  return typeTags.value
    .filter((tag) => !props.selectedIds.includes(tag.id))
    .map((tag) => ({ tag, rank: tagMatchRank(tag, search) }))
    .filter((candidate): candidate is { tag: SelectableTag; rank: MatchRank } => candidate.rank !== null)
    .sort(
      (left, right) =>
        compareMatchRank(left.rank, right.rank) ||
        left.tag.displayValue.localeCompare(right.tag.displayValue) ||
        left.tag.id - right.tag.id,
    )
    .slice(0, 10)
    .map((candidate) => candidate.tag)
})

type MatchRank = readonly [kind: number, position: number, length: number]

function normalizeSearchValue(value: string): string {
  return value.normalize('NFKC').trim().replace(/\s+/g, '_').toLocaleLowerCase()
}

function tagMatchRank(tag: SelectableTag, search: string): MatchRank | null {
  const values = [
    tag.englishValue,
    tag.displayValue,
    ...tag.translations.map((translation) => translation.value),
  ]
  if (search.includes(':')) values.push(tag.fullTag)
  const ranks = values
    .map((value) => valueMatchRank(normalizeSearchValue(value), search))
    .filter((rank): rank is MatchRank => rank !== null)
  return ranks.sort(compareMatchRank)[0] ?? null
}

function valueMatchRank(value: string, search: string): MatchRank | null {
  const position = value.indexOf(search)
  if (position < 0) return null
  if (value === search) return [0, 0, value.length]
  if (position === 0) return [1, 0, value.length]
  if (value[position - 1] === '_' || value[position - 1] === ':') {
    return [2, position, value.length]
  }
  return [3, position, value.length]
}

function compareMatchRank(left: MatchRank, right: MatchRank): number {
  return left[0] - right[0] || left[1] - right[1] || left[2] - right[2]
}

function secondaryValue(tag: SelectableTag): string | null {
  if (normalizeSearchValue(tag.displayValue) === normalizeSearchValue(tag.englishValue)) {
    return null
  }
  return tag.englishValue.replace(/_/g, ' ')
}

function selectTag(tagId: number): void {
  emit('select', tagId)
  query.value = ''
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && query.value) {
    event.preventDefault()
    query.value = ''
    return
  }
  if (matches.value.length === 0) {
    if (event.key === 'Enter' && query.value.trim()) event.preventDefault()
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % matches.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value =
      (activeIndex.value - 1 + matches.value.length) % matches.value.length
  } else if (event.key === 'Enter') {
    event.preventDefault()
    selectTag(matches.value[activeIndex.value < 0 ? 0 : activeIndex.value]!.id)
  }
}

watch(query, () => {
  activeIndex.value = -1
})
</script>

<template>
  <fieldset class="min-w-0">
    <legend class="mb-2 text-sm font-medium">{{ t(label) }}</legend>

    <div class="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
      <label :for="inputId" class="sr-only">{{ t('Search {label}', { label: t(label) }) }}</label>
      <input
        :id="inputId"
        v-model="query"
        type="search"
        maxlength="255"
        role="combobox"
        autocomplete="off"
        aria-autocomplete="list"
        :aria-controls="resultsId"
        :aria-expanded="query.trim().length > 0"
        :aria-activedescendant="activeIndex >= 0 ? `${resultsId}-${activeIndex}` : undefined"
        :placeholder="t('Search tags')"
        class="h-9 min-w-0 border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
        @keydown="handleKeydown"
      />
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line bg-surface px-3 text-sm font-medium hover:border-ink"
        @click="emit('create', query)"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Create tag') }}
      </button>
    </div>

    <ul v-if="selectedTags.length > 0" class="mt-3 flex min-w-0 flex-wrap gap-2">
      <li
        v-for="tag in selectedTags"
        :key="tag.id"
        class="flex min-w-0 max-w-full"
      >
        <TagChip
          :label="tag.displayValue.replace(/_/g, ' ')"
          selected
          :removable="!lockedIds?.includes(tag.id)"
          @activate="emit('remove', tag.id)"
        />
      </li>
    </ul>

    <div v-if="query.trim()" :id="resultsId" class="mt-2 border-y border-line" role="listbox">
      <button
        v-for="(tag, index) in matches"
        :id="`${resultsId}-${index}`"
        :key="tag.id"
        type="button"
        role="option"
        :aria-selected="index === activeIndex"
        class="flex min-h-10 w-full min-w-0 items-center justify-between gap-3 border-b border-line px-3 py-2 text-left text-sm last:border-b-0 hover:bg-canvas"
        :class="{ 'bg-accent-soft': index === activeIndex }"
        @mousemove="activeIndex = index"
        @click="selectTag(tag.id)"
      >
        <span class="min-w-0 break-words">{{ tag.displayValue.replace(/_/g, ' ') }}</span>
        <span v-if="secondaryValue(tag)" class="shrink-0 text-xs text-muted">
          {{ secondaryValue(tag) }}
        </span>
      </button>
      <p v-if="matches.length === 0" class="px-3 py-3 text-sm text-muted">
        {{ t('No matching tags') }}
      </p>
    </div>
  </fieldset>
</template>
