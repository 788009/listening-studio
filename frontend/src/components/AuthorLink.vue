<script setup lang="ts">
import { RouterLink } from 'vue-router'

import type { VoiceAuthor } from '@/api/voices'

defineProps<{
  author: VoiceAuthor
}>()
</script>

<template>
  <span class="inline-flex max-w-full min-w-0 items-baseline gap-1.5">
    <RouterLink
      :to="`/user/${author.userId}`"
      class="min-w-0 break-words hover:text-accent"
    >
      {{ author.username || author.userId }}
    </RouterLink>
    <span class="shrink-0 text-muted">@{{ author.userId }}</span>
  </span>
</template>
