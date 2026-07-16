<script setup lang="ts">
import { computed } from 'vue'

import type { ResourceStatus } from '@/api/voices'

const props = defineProps<{ status: ResourceStatus }>()

const label = computed(() => {
  const labels: Record<ResourceStatus, string> = {
    pending: 'Pending',
    processing: 'Processing',
    ready: 'Ready',
    failed: 'Failed',
  }
  return labels[props.status]
})

const classes = computed(() => ({
  'text-muted': props.status === 'pending',
  'text-warning': props.status === 'processing',
  'text-success': props.status === 'ready',
  'text-danger': props.status === 'failed',
}))
</script>

<template>
  <span class="inline-flex items-center gap-2 text-sm font-medium" :class="classes">
    <svg
      v-if="status === 'processing'"
      class="h-4 w-4 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path d="M12 3a9 9 0 1 1-9 9" stroke="currentColor" stroke-width="2" />
    </svg>
    <span v-else class="h-2 w-2 bg-current" aria-hidden="true"></span>
    {{ label }}
  </span>
</template>
