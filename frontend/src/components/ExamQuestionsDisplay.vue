<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { AudioQuestion } from '@/api/audios'
import { useI18n } from '@/i18n'

interface ExamOption {
  id: string
  text: string
  correct: boolean
}

interface ExamQuestion {
  id: number
  prompt: string
  options: ExamOption[]
}

const props = defineProps<{
  title: string
  questions: AudioQuestion[]
}>()

const { t } = useI18n()
const examQuestions = ref<ExamQuestion[]>([])

function optionLabel(index: number): string {
  let value = index + 1
  let label = ''
  while (value > 0) {
    value -= 1
    label = String.fromCharCode(65 + (value % 26)) + label
    value = Math.floor(value / 26)
  }
  return label
}

function shuffledOptions(question: AudioQuestion, previousOptions?: ExamOption[]): ExamOption[] {
  const options = [
    ...question.correctAnswers.map((text, index) => ({
      id: `correct-${index}`,
      text,
      correct: true,
    })),
    ...question.incorrectAnswers.map((text, index) => ({
      id: `incorrect-${index}`,
      text,
      correct: false,
    })),
  ]

  for (let index = options.length - 1; index > 0; index -= 1) {
    const replacementIndex = Math.floor(Math.random() * (index + 1))
    ;[options[index], options[replacementIndex]] = [options[replacementIndex]!, options[index]!]
  }

  if (
    options.length > 1 &&
    previousOptions?.every((option, index) => option.id === options[index]?.id)
  ) {
    options.push(options.shift()!)
  }
  return options
}

function randomizeOptions(): void {
  const previousByQuestionId = new Map(
    examQuestions.value.map((question) => [question.id, question.options]),
  )
  examQuestions.value = props.questions.map((question) => ({
    id: question.id,
    prompt: question.prompt,
    options: shuffledOptions(question, previousByQuestionId.get(question.id)),
  }))
}

const questionText = computed(() =>
  examQuestions.value
    .map((question, index) => {
      const options = question.options
        .map((option, optionIndex) => `${optionLabel(optionIndex)}. ${option.text}`)
        .join('\n')
      return `${index + 1}. ${question.prompt}\n${options}`
    })
    .join('\n\n'),
)

const answerText = computed(() => {
  const answers = examQuestions.value.map((question) =>
    question.options
      .flatMap((option, index) => (option.correct ? [optionLabel(index)] : []))
      .join(''),
  )
  return answers.reduce<string[]>((lines, answer, index) => {
    const lineIndex = Math.floor(index / 5)
    lines[lineIndex] = `${lines[lineIndex] ?? ''}${answer}`
    return lines
  }, []).join('\n')
})

const paperText = computed(
  () => `${t('Questions')}\n${questionText.value}\n\n${t('Answers')}\n${answerText.value}`,
)

function copyWithFallback(text: string): void {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.className = 'fixed left-0 top-0 -z-10 opacity-0'
  document.body.append(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

async function copyPaper(): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(paperText.value)
      return
    } catch {
      // Use the document API when clipboard permission is unavailable.
    }
  }
  copyWithFallback(paperText.value)
}

function downloadPaper(): void {
  const blob = new Blob([paperText.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.title.replace(/[\\/:*?"<>|]/g, '_') || 'questions'}-questions.txt`
  link.click()
  URL.revokeObjectURL(url)
}

watch(() => props.questions, randomizeOptions, { deep: true, immediate: true })
</script>

<template>
  <div class="min-w-0">
    <div class="mb-4 flex flex-wrap justify-end gap-2">
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink"
        @click="copyPaper"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <rect x="8" y="8" width="11" height="11" stroke="currentColor" stroke-width="2" />
          <path d="M16 8V5H5v11h3" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Copy') }}
      </button>
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink"
        @click="downloadPaper"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Download') }}
      </button>
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink"
        @click="randomizeOptions"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M4 7h3l10 10h3m0 0v-3m0 3h-3M4 17h3l3-3m4-4 3-3h3m0 0V4m0 3h-3" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Randomize options') }}
      </button>
    </div>

    <section>
      <h3 class="mb-2 text-sm font-medium">{{ t('Questions') }}</h3>
      <pre class="overflow-x-auto border border-line bg-surface-alt p-4 text-sm leading-6"><code>{{ questionText }}</code></pre>
    </section>
    <section class="mt-5">
      <h3 class="mb-2 text-sm font-medium">{{ t('Answers') }}</h3>
      <pre class="overflow-x-auto border border-line bg-surface-alt p-4 text-sm leading-6"><code>{{ answerText }}</code></pre>
    </section>
  </div>
</template>
