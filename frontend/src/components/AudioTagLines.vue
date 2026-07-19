<script setup lang="ts">
import { computed } from 'vue'

import type { AudioTag, AudioTagType } from '@/api/audios'
import TagChip from '@/components/TagChip.vue'
import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    tags: AudioTag[]
    includeAuthor?: boolean
    includeVoice?: boolean
    searchPath?: string
    grouped?: boolean
  }>(),
  { includeAuthor: true, includeVoice: true, searchPath: undefined, grouped: false },
)
const { t } = useI18n()

const rows = computed(() => {
  const labels: Record<AudioTagType, string> = {
    author: t('Author'),
    voice: t('Voice'),
    topic: t('Topic'),
    category: t('Category'),
    other: t('Other'),
  }
  const types: AudioTagType[] = [
    ...(props.includeAuthor ? (['author'] as const) : []),
    ...(props.includeVoice ? (['voice'] as const) : []),
    'topic',
    'category',
    'other',
  ]
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
  <dl v-if="grouped" class="space-y-3">
    <div
      v-for="row in rows"
      :key="row.type"
      class="grid min-w-0 gap-2 sm:grid-cols-[5rem_minmax(0,1fr)] sm:items-start"
    >
      <dt class="pt-1 text-sm text-muted">{{ row.label }}</dt>
      <dd class="min-w-0">
        <ul class="flex min-w-0 flex-wrap gap-2">
          <li v-for="tag in row.values" :key="tag.id" class="flex min-w-0 max-w-full">
            <TagChip
              :label="tag.displayValue.replace(/_/g, ' ')"
              :to="searchPath ? { path: searchPath, query: { q: tag.fullTag } } : undefined"
            />
          </li>
        </ul>
      </dd>
    </div>
  </dl>
  <ul v-else class="flex min-w-0 flex-wrap gap-2">
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
