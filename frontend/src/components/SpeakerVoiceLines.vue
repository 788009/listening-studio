<script setup lang="ts">
import { computed } from 'vue'

import type { AudioUtterance } from '@/api/audios'
import TagChip from '@/components/TagChip.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{ utterances: AudioUtterance[] }>()
const { t } = useI18n()

const pairs = computed(() => {
  const seen = new Set<string>()
  return props.utterances.filter((utterance) => {
    const key = `${utterance.speakerDisplayName}\u0000${utterance.voiceId ?? 'none'}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
</script>

<template>
  <div v-if="pairs.length > 0" class="grid min-w-0 gap-3 sm:grid-cols-[5rem_minmax(0,1fr)]">
    <dt class="pt-1 text-sm text-muted">{{ t('Speakers') }}</dt>
    <dd class="min-w-0">
      <ul class="space-y-2">
        <li v-for="utterance in pairs" :key="`${utterance.speakerDisplayName}-${utterance.voiceId}`" class="flex min-w-0 flex-wrap items-center gap-2 text-sm">
          <span class="min-w-0 break-words">{{ utterance.speakerDisplayName }}</span>
          <svg v-if="utterance.voiceTitle" viewBox="0 0 16 16" fill="none" class="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true">
            <path d="M3 8h10m-3-3 3 3-3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <TagChip
            v-if="utterance.voiceTitle"
            :label="utterance.voiceTitle"
            :to="utterance.speakerTag ? { path: '/audio', query: { q: utterance.speakerTag } } : undefined"
          />
        </li>
      </ul>
    </dd>
  </div>
</template>
