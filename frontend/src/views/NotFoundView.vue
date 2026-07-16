<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from '@/i18n'

const { t } = useI18n()
</script>

<template>
  <section class="py-12 text-center" aria-labelledby="not-found-title">
    <p class="mb-2 text-sm font-medium text-danger">404</p>
    <h1 id="not-found-title" class="text-2xl font-semibold">{{ t('Page not found') }}</h1>
    <RouterLink
      to="/"
      class="mt-6 inline-flex h-10 items-center border border-ink bg-ink px-4 text-sm font-medium text-white hover:bg-accent focus:outline-none focus:shadow-focus"
    >
      {{ t('Back to library') }}
    </RouterLink>
  </section>
</template>
