<script setup lang="ts">
import { computed } from 'vue'

import type { VoiceTag, VoiceTagType } from '@/api/voices'
import TagChip from '@/components/TagChip.vue'
import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    tags: VoiceTag[]
    includeAuthor?: boolean
    searchPath?: string
  }>(),
  { includeAuthor: true, searchPath: undefined },
)
const { t } = useI18n()

const rows = computed(() => {
  const labels: Record<VoiceTagType, string> = {
    author: t('Author'),
    gender: t('Gender'),
  }
  const types: VoiceTagType[] = props.includeAuthor
    ? ['author', 'gender']
    : ['gender']
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
