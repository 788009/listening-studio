<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<template>
  <a
    href="#main-content"
    class="sr-only z-50 bg-surface px-3 py-2 text-sm font-medium text-ink focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
  >
    Skip to content
  </a>
  <div class="min-h-screen bg-canvas text-ink">
    <header class="border-b border-line bg-surface">
      <div
        class="mx-auto flex min-h-16 max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2 sm:px-6 lg:px-8"
      >
        <RouterLink class="flex items-center gap-3" to="/">
          <img class="h-8 w-8" src="/mark.svg" alt="" />
          <span class="text-base font-semibold">Listening Studio</span>
        </RouterLink>
        <nav aria-label="Primary navigation" class="flex h-10 items-center gap-1">
          <RouterLink
            to="/"
            class="flex h-9 items-center border-b-2 border-transparent px-3 text-sm font-medium text-muted hover:text-ink"
            active-class="border-accent text-ink"
          >
            Library
          </RouterLink>
          <RouterLink
            to="/create"
            class="flex h-9 items-center border-b-2 border-transparent px-3 text-sm font-medium text-muted hover:text-ink"
            active-class="border-accent text-ink"
          >
            Create
          </RouterLink>
          <RouterLink
            v-if="auth.isTeacher"
            to="/generate"
            class="flex h-9 items-center border-b-2 border-transparent px-3 text-sm font-medium text-muted hover:text-ink"
            active-class="border-accent text-ink"
          >
            Batch
          </RouterLink>
          <RouterLink
            v-if="auth.isTeacher"
            to="/voices"
            class="flex h-9 items-center border-b-2 border-transparent px-3 text-sm font-medium text-muted hover:text-ink"
            active-class="border-accent text-ink"
          >
            Voices
          </RouterLink>
        </nav>
      </div>
    </header>

    <main id="main-content" class="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <RouterView />
    </main>
  </div>
</template>
