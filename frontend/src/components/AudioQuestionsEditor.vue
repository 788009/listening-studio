<script setup lang="ts">
import type { AudioQuestionInput } from '@/api/audios'
import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    modelValue: AudioQuestionInput[]
    embedded?: boolean
  }>(),
  { embedded: false },
)
const emit = defineEmits<{
  'update:modelValue': [value: AudioQuestionInput[]]
}>()
const { t } = useI18n()
const answerFields = ['correctAnswers', 'incorrectAnswers'] as const

function updateQuestion(index: number, update: Partial<AudioQuestionInput>): void {
  emit(
    'update:modelValue',
    props.modelValue.map((question, position) =>
      position === index ? { ...question, ...update } : question,
    ),
  )
}

function addQuestion(): void {
  emit('update:modelValue', [
    ...props.modelValue,
    { prompt: '', correctAnswers: [''], incorrectAnswers: [''] },
  ])
}

function removeQuestion(index: number): void {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, position) => position !== index),
  )
}

function updateAnswer(
  questionIndex: number,
  field: 'correctAnswers' | 'incorrectAnswers',
  answerIndex: number,
  value: string,
): void {
  const question = props.modelValue[questionIndex]
  if (!question) return
  const answers = [...question[field]]
  answers[answerIndex] = value
  updateQuestion(questionIndex, { [field]: answers })
}

function addAnswer(
  questionIndex: number,
  field: 'correctAnswers' | 'incorrectAnswers',
): void {
  const question = props.modelValue[questionIndex]
  if (!question) return
  updateQuestion(questionIndex, {
    [field]: [...question[field], ''],
  })
}

function removeAnswer(
  questionIndex: number,
  field: 'correctAnswers' | 'incorrectAnswers',
  answerIndex: number,
): void {
  const question = props.modelValue[questionIndex]
  if (!question) return
  const answers = question[field]
  if (answers.length <= 1) return
  updateQuestion(questionIndex, {
    [field]: answers.filter((_, position) => position !== answerIndex),
  })
}
</script>

<template>
  <section
    :class="embedded ? 'min-w-0 border-t border-line pt-5' : 'min-w-0 border-b border-line px-5 py-6'"
    aria-labelledby="audio-questions-title"
  >
    <div class="flex min-w-0 items-center justify-between gap-4">
      <h2 id="audio-questions-title" class="text-sm font-semibold">{{ t('Questions') }}</h2>
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink"
        @click="addQuestion"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Add question') }}
      </button>
    </div>

    <p v-if="modelValue.length === 0" class="mt-4 text-sm text-muted">{{ t('No questions') }}</p>
    <ol v-else class="mt-5 divide-y divide-line border-y border-line">
      <li v-for="(question, questionIndex) in modelValue" :key="questionIndex" class="py-5">
        <div class="flex min-w-0 items-start gap-3">
          <span class="flex h-7 w-7 shrink-0 items-center justify-center border border-line text-sm font-medium">
            {{ questionIndex + 1 }}
          </span>
          <div class="min-w-0 flex-1">
            <label :for="`question-prompt-${questionIndex}`" class="mb-1 block text-sm font-medium">
              {{ t('Question prompt') }}
            </label>
            <textarea
              :id="`question-prompt-${questionIndex}`"
              :value="question.prompt"
              rows="2"
              class="w-full resize-y border border-line px-3 py-2 text-sm leading-6 focus:border-accent focus:outline-none focus:shadow-focus"
              @input="updateQuestion(questionIndex, { prompt: ($event.target as HTMLTextAreaElement).value })"
            ></textarea>
          </div>
          <button
            type="button"
            class="flex h-8 w-8 shrink-0 items-center justify-center text-muted hover:text-danger"
            :title="t('Remove question')"
            :aria-label="t('Remove question {position}', { position: questionIndex + 1 })"
            @click="removeQuestion(questionIndex)"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
              <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13" stroke="currentColor" stroke-width="2" />
            </svg>
          </button>
        </div>

        <div class="mt-4 grid gap-5 pl-10 md:grid-cols-2">
          <div v-for="field in answerFields" :key="field">
            <p class="text-sm font-medium">
              {{ field === 'correctAnswers' ? t('Correct answers') : t('Incorrect answers') }}
            </p>
            <div class="mt-2 space-y-2">
              <div v-for="(answer, answerIndex) in question[field]" :key="answerIndex" class="flex gap-2">
                <input
                  :id="`question-${questionIndex}-${field}-${answerIndex}`"
                  :value="answer"
                  type="text"
                  class="h-9 min-w-0 flex-1 border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
                  :aria-label="`${field === 'correctAnswers' ? t('Correct answer') : t('Incorrect answer')} ${answerIndex + 1}`"
                  @input="updateAnswer(questionIndex, field, answerIndex, ($event.target as HTMLInputElement).value)"
                />
                <button
                  v-if="question[field].length > 1"
                  type="button"
                  class="flex h-9 w-9 shrink-0 items-center justify-center text-muted hover:text-danger"
                  :title="t('Remove answer')"
                  :aria-label="t('Remove answer')"
                  @click="removeAnswer(questionIndex, field, answerIndex)"
                >
                  <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                    <path d="M5 12h14" stroke="currentColor" stroke-width="2" />
                  </svg>
                </button>
              </div>
            </div>
            <button
              type="button"
              class="mt-2 inline-flex h-8 items-center gap-1 text-sm font-medium text-accent hover:underline"
              @click="addAnswer(questionIndex, field)"
            >
              <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
                <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" />
              </svg>
              {{ t('Add answer') }}
            </button>
          </div>
        </div>
      </li>
    </ol>
  </section>
</template>
