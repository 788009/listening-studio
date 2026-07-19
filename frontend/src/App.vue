<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'

import AuthControls from '@/components/AuthControls.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/i18n'

const auth = useAuthStore()
const { t } = useI18n()
</script>

<template>
  <a
    href="#main-content"
    class="sr-only z-50 rounded-md bg-surface px-3 py-2 text-sm font-medium text-ink shadow-panel focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
  >
    {{ t('Skip to content') }}
  </a>

  <div class="min-h-screen bg-canvas text-ink">
    <aside
      class="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-surface lg:flex"
    >
      <RouterLink class="flex h-20 items-center gap-3 px-6" to="/">
        <img class="h-9 w-9" src="/mark.svg" alt="" />
        <span class="text-[15px] font-semibold">Listening Studio</span>
      </RouterLink>

      <nav :aria-label="t('Primary navigation')" class="flex-1 overflow-y-auto px-3 py-3">
        <p class="px-3 pb-2 text-xs font-medium text-muted">{{ t('Browse') }}</p>
        <RouterLink
          to="/"
          exact-active-class="bg-accent-soft text-accent"
          class="mb-1 flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true">
            <path d="M3 10.5 12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5v-9Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
            <path d="M9 21v-7h6v7" stroke="currentColor" stroke-width="1.8" />
          </svg>
          {{ t('Home') }}
        </RouterLink>
        <RouterLink
          to="/audio"
          active-class="bg-accent-soft text-accent"
          class="flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true">
            <path d="M4 7.5h16M4 12h16M4 16.5h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
          {{ t('Library') }}
        </RouterLink>

        <template v-if="auth.isTeacher">
          <p class="mt-7 px-3 pb-2 text-xs font-medium text-muted">{{ t('Workspace') }}</p>
          <RouterLink to="/create" active-class="bg-accent-soft text-accent" class="mb-1 flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
            {{ t('Create') }}
          </RouterLink>
          <RouterLink to="/generate" active-class="bg-accent-soft text-accent" class="mb-1 flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /><path d="m17 15 3 2-3 2v-4Z" fill="currentColor" /></svg>
            {{ t('Batch') }}
          </RouterLink>
          <RouterLink to="/papers/new" active-class="bg-accent-soft text-accent" class="mb-1 flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M6 3.5h9l3 3V21H6V3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" /><path d="M9 11h6M9 15h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
            {{ t('Papers') }}
          </RouterLink>
          <RouterLink to="/voices" active-class="bg-accent-soft text-accent" class="mb-1 flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M4 14h2M8 9v10M12 5v14M16 8v8M20 11v2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
            {{ t('Voices') }}
          </RouterLink>
          <RouterLink to="/manage" active-class="bg-accent-soft text-accent" class="flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted transition-colors hover:bg-raised hover:text-ink">
            <svg viewBox="0 0 24 24" fill="none" class="h-[18px] w-[18px]" aria-hidden="true"><path d="M4 7h16M7 12h10M9 17h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
            {{ t('Manage') }}
          </RouterLink>
        </template>
      </nav>

      <div class="border-t border-line p-3">
        <div class="mb-2 flex items-center justify-between px-2">
          <span class="text-xs text-muted">{{ t('Appearance') }}</span>
          <ThemeToggle />
        </div>
        <AuthControls />
      </div>
    </aside>

    <div class="lg:pl-60">
      <header class="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur lg:hidden">
        <div class="flex h-16 items-center justify-between gap-3 px-4 sm:px-6">
          <RouterLink class="flex min-w-0 items-center gap-2.5" to="/">
            <img class="h-8 w-8 shrink-0" src="/mark.svg" alt="" />
            <span class="truncate text-sm font-semibold">Listening Studio</span>
          </RouterLink>
          <div class="flex shrink-0 items-center gap-1">
            <ThemeToggle />
            <AuthControls />
          </div>
        </div>
        <nav :aria-label="t('Primary navigation')" class="scrollbar-none flex gap-1 overflow-x-auto px-3 pb-2 sm:px-5">
          <RouterLink to="/" exact-active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Home') }}</RouterLink>
          <RouterLink to="/audio" active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Library') }}</RouterLink>
          <template v-if="auth.isTeacher">
            <RouterLink to="/create" active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Create') }}</RouterLink>
            <RouterLink to="/generate" active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Batch') }}</RouterLink>
            <RouterLink to="/papers/new" active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Papers') }}</RouterLink>
            <RouterLink to="/voices" active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Voices') }}</RouterLink>
            <RouterLink to="/manage" active-class="bg-accent-soft text-accent" class="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-muted">{{ t('Manage') }}</RouterLink>
          </template>
        </nav>
      </header>

      <main id="main-content" class="app-content mx-auto w-full max-w-[90rem] px-4 py-7 sm:px-6 sm:py-9 lg:px-10 lg:py-10 xl:px-12">
        <RouterView />
      </main>
    </div>
  </div>
</template>
