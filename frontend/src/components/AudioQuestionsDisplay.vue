<script setup lang="ts">
import type { AudioQuestion } from '@/api/audios'
import { useI18n } from '@/i18n'

defineProps<{ questions: AudioQuestion[] }>()
const { t } = useI18n()
</script>

<template>
  <ol class="min-w-0 divide-y divide-line border-y border-line">
    <li v-for="(question, index) in questions" :key="question.id" class="py-5 first:pt-0 last:pb-0">
      <div class="flex min-w-0 gap-3">
        <span class="flex h-7 w-7 shrink-0 items-center justify-center border border-line text-sm font-medium">
          {{ index + 1 }}
        </span>
        <p class="min-w-0 break-words text-sm font-medium leading-6">{{ question.prompt }}</p>
      </div>
      <div class="mt-3 grid gap-4 pl-10 md:grid-cols-2">
        <div>
          <h3 class="text-xs font-medium text-muted">{{ t('Correct answers') }}</h3>
          <ul class="mt-2 space-y-1.5">
            <li v-for="(answer, answerIndex) in question.correctAnswers" :key="answerIndex" class="break-words border-l-2 border-success pl-3 text-sm leading-6">
              {{ answer }}
            </li>
          </ul>
        </div>
        <div>
          <h3 class="text-xs font-medium text-muted">{{ t('Incorrect answers') }}</h3>
          <ul class="mt-2 space-y-1.5">
            <li v-for="(answer, answerIndex) in question.incorrectAnswers" :key="answerIndex" class="break-words border-l-2 border-line pl-3 text-sm leading-6">
              {{ answer }}
            </li>
          </ul>
        </div>
      </div>
    </li>
  </ol>
</template>
