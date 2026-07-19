<script setup lang="ts">
import { computed } from 'vue'

import type { AudioTag, AudioTagType } from '@/api/audios'
import TagChip from '@/components/TagChip.vue'
import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    tags: AudioTag[]
    includeAuthor?: boolean
    searchPath?: string
  }>(),
  { includeAuthor: true, searchPath: undefined },
)
const { t } = useI18n()

const rows = computed(() => {
  const labels: Record<AudioTagType, string> = {
    author: t('Author'),
    speaker: t('Speaker'),
    topic: t('Topic'),
    category: t('Category'),
  }
  const types: AudioTagType[] = props.includeAuthor
    ? ['author', 'speaker', 'topic', 'category']
    : ['speaker', 'topic', 'category']
  return types
    .map((type) => ({
      type,
      label: labels[type],
      values: props.tags.filter((tag) => tag.type === type),
    }))
    .filter((row) => row.values.length > 0)
})
</script>

<template>
  <ul class="flex min-w-0 flex-wrap gap-2">
    <template
      v-for="row in rows"
      :key="row.type"
    >
      <li v-for="tag in row.values" :key="tag.id" class="flex min-w-0 max-w-full">
        <TagChip
          :label="tag.displayValue.replace(/_/g, ' ')"
          :type-label="row.label"
          :to="searchPath ? { path: searchPath, query: { q: tag.fullTag } } : undefined"
        />
      </li>
    </template>
  </ul>
</template>
