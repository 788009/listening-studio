<script setup lang="ts">
import { RouterLink } from 'vue-router'

import type { VoiceAuthor } from '@/api/voices'

defineProps<{
  author: VoiceAuthor
}>()
</script>

<template>
  <RouterLink
    :to="`/user/${author.userId}`"
    class="inline-flex max-w-full min-w-0 items-baseline gap-1.5 hover:text-accent"
  >
    <span class="min-w-0 break-words">{{ author.username || author.userId }}</span>
    <span class="shrink-0 text-muted">@{{ author.userId }}</span>
  </RouterLink>
</template>
