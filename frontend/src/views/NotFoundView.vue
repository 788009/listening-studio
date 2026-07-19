<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from '@/i18n'

const { t } = useI18n()
</script>

<template>
  <section class="mx-auto max-w-lg py-16 text-center" aria-labelledby="not-found-title">
    <span class="mx-auto flex h-12 w-12 items-center justify-center rounded-md bg-raised text-sm font-semibold text-muted">404</span>
    <h1 id="not-found-title" class="mt-5 text-3xl font-semibold">{{ t('Page not found') }}</h1>
    <RouterLink
      to="/"
      class="mt-6 inline-flex h-10 items-center border border-ink bg-ink px-4 text-sm font-medium text-white hover:bg-accent focus:outline-none focus:shadow-focus"
    >
      {{ t('Back home') }}
    </RouterLink>
  </section>
</template>
