<script setup lang="ts">
import { computed } from 'vue'

import { useI18n } from '@/i18n'

interface ProgressStage {
  threshold: number
  label: string
}

const props = defineProps<{
  progress: number
  queued: boolean
  queuedLabel: string
  stages: ProgressStage[]
  taskLabel: string
  progressLabel: string
}>()
const { t } = useI18n()

const normalizedProgress = computed(() =>
  Math.min(100, Math.max(0, Math.round(props.progress))),
)
const currentStageIndex = computed(() => {
  if (props.queued) return -1
  let result = 0
  for (const [index, stage] of props.stages.entries()) {
    if (normalizedProgress.value < stage.threshold) break
    result = index
  }
  return result
})
const currentLabel = computed(() =>
  props.queued
    ? props.queuedLabel
    : props.stages[currentStageIndex.value]?.label ?? props.queuedLabel,
)
const stageSummary = computed(() =>
  t('Stage {current} of {total}', {
    current: currentStageIndex.value + 1,
    total: props.stages.length,
  }),
)
const stageGrid = computed(() => ({
  gridTemplateColumns: `repeat(${Math.max(1, props.stages.length)}, minmax(0, 1fr))`,
}))
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <p class="flex min-w-0 items-center gap-2 text-base font-semibold" role="status" aria-live="polite">
          <svg v-if="!queued" viewBox="0 0 24 24" fill="none" class="h-4 w-4 shrink-0 animate-spin text-accent motion-reduce:animate-none" aria-hidden="true">
            <path d="M12 3a9 9 0 1 1-9 9" stroke="currentColor" stroke-width="2" />
          </svg>
          <span class="min-w-0 break-words">{{ currentLabel }}</span>
        </p>
        <p class="mt-1 text-sm text-muted">{{ taskLabel }}</p>
      </div>
      <span class="shrink-0 text-sm font-medium tabular-nums">{{ normalizedProgress }}%</span>
    </div>

    <div
      class="relative mt-5 h-2 overflow-hidden bg-canvas"
      role="progressbar"
      :aria-label="progressLabel"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="normalizedProgress"
      :aria-valuetext="currentLabel"
    >
      <div
        class="h-full bg-accent transition-[width] motion-reduce:transition-none"
        :style="{ width: `${normalizedProgress}%` }"
      />
      <span v-if="!queued" class="job-progress-activity" aria-hidden="true"></span>
    </div>

    <div class="mt-3 flex items-center justify-between gap-4">
      <div class="grid min-w-0 flex-1 gap-1" :style="stageGrid" aria-hidden="true">
        <span
          v-for="(stage, index) in stages"
          :key="stage.threshold"
          class="h-1"
          :class="index <= currentStageIndex ? 'bg-accent' : 'bg-line'"
        ></span>
      </div>
      <span class="shrink-0 text-xs text-muted">{{ stageSummary }}</span>
    </div>
  </div>
</template>

<style scoped>
.job-progress-activity {
  position: absolute;
  inset-block: 0;
  left: 0;
  width: 18%;
  background-color: rgb(var(--color-accent) / 0.24);
  animation: job-progress-activity 1.8s linear infinite;
}

@keyframes job-progress-activity {
  from {
    transform: translateX(-100%);
  }

  to {
    transform: translateX(560%);
  }
}
</style>
