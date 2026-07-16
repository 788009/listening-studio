<script setup lang="ts">
import { RouterLink } from 'vue-router'

import type { ManagedResource } from '@/api/resourceManagement'
import { useI18n } from '@/i18n'

const { formatDate, t } = useI18n()

defineProps<{
  items: ManagedResource[]
  selectable: boolean
  selectedIds: Set<number>
  busy?: boolean
}>()
const emit = defineEmits<{
  select: [id: number]
  delete: [item: ManagedResource]
}>()

const referenceLabels: Record<string, string> = {
  active_task: 'active task',
  audio_utterance: 'audio utterance',
  generation_batch: 'generation batch',
  voice_sample: 'voice sample',
  paper_item: 'paper item',
  paper_result: 'paper result',
}

function detailPath(item: ManagedResource): string | null {
  if (item.kind === 'voice') return `/voice/${item.id}`
  if (item.kind === 'audio') return `/audio/${item.id}`
  if (item.kind === 'generation_batch') return `/generate/${item.id}`
  return null
}

function references(item: ManagedResource): string {
  return item.references
    .map((value) => `${value.count} ${t(referenceLabels[value.type] ?? value.type)}`)
    .join(', ')
}

function tagLabel(type: string): string {
  return t(type.charAt(0).toUpperCase() + type.slice(1))
}

function statusClass(status: string): string {
  if (status === 'ready' || status === 'completed') return 'text-success'
  if (status === 'failed' || status === 'cancelled') return 'text-danger'
  if (status === 'processing') return 'text-warning'
  return 'text-muted'
}
</script>

<template>
  <ul class="divide-y divide-line border-y border-line bg-surface">
    <li
      v-for="item in items"
      :key="`${item.kind}-${item.id}`"
      class="grid min-w-0 gap-4 px-4 py-5 sm:grid-cols-[auto_minmax(0,1fr)_8rem] sm:items-start"
      :class="selectable ? 'grid-cols-[auto_minmax(0,1fr)]' : 'grid-cols-1'"
    >
      <div v-if="selectable" class="pt-0.5">
        <input
          type="checkbox"
          class="h-4 w-4 accent-accent"
          :checked="selectedIds.has(item.id)"
          :disabled="busy"
          :aria-label="t('Select {title}', { title: item.title })"
          @change="emit('select', item.id)"
        />
      </div>
      <div v-else class="hidden sm:block" aria-hidden="true"></div>

      <div class="min-w-0">
        <RouterLink
          v-if="detailPath(item)"
          :to="detailPath(item) ?? '/'"
          class="break-words text-sm font-semibold hover:text-accent hover:underline"
        >
          {{ item.title }}
        </RouterLink>
        <p v-else class="break-words text-sm font-semibold">{{ item.title }}</p>
        <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span :class="statusClass(item.status)" class="font-medium capitalize">
            {{ t(item.status.charAt(0).toUpperCase() + item.status.slice(1)) }}
          </span>
          <span v-if="item.visibility" class="capitalize">
            {{ t(item.visibility.charAt(0).toUpperCase() + item.visibility.slice(1)) }}
          </span>
          <time :datetime="item.createdAt">{{ formatDate(item.createdAt) }}</time>
        </div>
        <p v-if="item.tags.length > 0" class="mt-2 break-words text-xs text-muted">
          {{ item.tags.map((tag) => `${tagLabel(tag.type)}: ${tag.value.replace(/_/g, ' ')}`).join(', ') }}
        </p>
        <p v-if="item.references.length > 0" class="mt-2 break-words text-xs text-danger">
          {{ t('Referenced by {references}', { references: references(item) }) }}
        </p>
      </div>

      <button
        v-if="item.kind === 'voice' || item.kind === 'audio'"
        type="button"
        :disabled="busy || !item.canDelete"
        class="col-span-2 inline-flex h-9 items-center justify-center gap-2 border border-line px-3 text-sm font-medium text-danger hover:border-danger disabled:text-muted disabled:opacity-60 sm:col-span-1"
        :title="item.canDelete ? t('Delete') : t('Referenced resources cannot be deleted')"
        @click="emit('delete', item)"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Delete') }}
      </button>
    </li>
  </ul>
</template>
