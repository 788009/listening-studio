<script setup lang="ts">
import { computed, ref, useId } from 'vue'

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
}>()
const emit = defineEmits<{
  select: [tagId: number]
  remove: [tagId: number]
  create: [query: string]
}>()
const { t } = useI18n()
const query = ref('')
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
    .filter((tag) => !props.selectedIds.includes(tag.id) && tagMatches(tag, search))
    .slice(0, 10)
})

function normalizeSearchValue(value: string): string {
  return value.normalize('NFKC').trim().replace(/\s+/g, '_').toLocaleLowerCase()
}

function tagMatches(tag: SelectableTag, search: string): boolean {
  return [
    tag.englishValue,
    tag.displayValue,
    tag.fullTag,
    ...tag.translations.map((translation) => translation.value),
  ].some((value) => normalizeSearchValue(value).includes(search))
}

function selectTag(tagId: number): void {
  emit('select', tagId)
  query.value = ''
}
</script>

<template>
  <fieldset class="min-w-0">
    <legend class="mb-2 text-sm font-medium">{{ t(label) }}</legend>

    <ul v-if="selectedTags.length > 0" class="mb-3 divide-y divide-line border-y border-line">
      <li
        v-for="tag in selectedTags"
        :key="tag.id"
        class="flex min-w-0 items-center justify-between gap-3 py-2 text-sm"
      >
        <span class="min-w-0 break-words">{{ tag.displayValue.replace(/_/g, ' ') }}</span>
        <button
          type="button"
          class="inline-flex h-8 w-8 shrink-0 items-center justify-center text-muted hover:text-danger"
          :aria-label="t('Remove {tag}', { tag: tag.displayValue.replace(/_/g, ' ') })"
          :title="t('Remove tag')"
          @click="emit('remove', tag.id)"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
            <path d="M5 5l14 14M19 5 5 19" stroke="currentColor" stroke-width="2" />
          </svg>
        </button>
      </li>
    </ul>

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
        :placeholder="t('Search tags')"
        class="h-9 min-w-0 border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
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

    <div v-if="query.trim()" :id="resultsId" class="mt-2 border-y border-line" role="listbox">
      <button
        v-for="tag in matches"
        :key="tag.id"
        type="button"
        role="option"
        aria-selected="false"
        class="flex min-h-10 w-full min-w-0 items-center justify-between gap-3 border-b border-line px-3 py-2 text-left text-sm last:border-b-0 hover:bg-canvas"
        @click="selectTag(tag.id)"
      >
        <span class="min-w-0 break-words">{{ tag.displayValue.replace(/_/g, ' ') }}</span>
        <span class="shrink-0 text-xs text-muted">{{ tag.englishValue }}</span>
      </button>
      <p v-if="matches.length === 0" class="px-3 py-3 text-sm text-muted">
        {{ t('No matching tags') }}
      </p>
    </div>
  </fieldset>
</template>
