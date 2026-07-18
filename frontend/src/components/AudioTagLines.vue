<script setup lang="ts">
import { computed } from 'vue'

import type { AudioTag, AudioTagType } from '@/api/audios'
import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    tags: AudioTag[]
    includeAuthor?: boolean
  }>(),
  { includeAuthor: true },
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
  <dl class="space-y-2">
    <div
      v-for="row in rows"
      :key="row.type"
      class="grid min-w-0 grid-cols-[4.75rem_minmax(0,1fr)] gap-2 text-sm"
    >
      <dt class="text-muted">{{ row.label }}</dt>
      <dd class="min-w-0 break-words text-ink">
        {{ row.values.map((tag) => tag.displayValue.replace(/_/g, ' ')).join(', ') }}
      </dd>
    </div>
  </dl>
</template>
