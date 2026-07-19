<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { TagTranslation } from '@/api/voices'
import TagChip from '@/components/TagChip.vue'
import { supportedLocales, useI18n } from '@/i18n'

type EditableTagType = 'gender' | 'topic' | 'category'

const props = defineProps<{
  open: boolean
  type: EditableTagType | null
  initialEnglishValue: string
  busy: boolean
  errorMessage: string
}>()
const emit = defineEmits<{
  close: []
  submit: [input: { englishValue: string; translations: TagTranslation[] }]
}>()
const { t } = useI18n()
const dialog = ref<HTMLElement | null>(null)
const englishInput = ref<HTMLInputElement | null>(null)
const englishValue = ref('')
const translationValues = ref<Record<string, string>>({})
const validationMessage = ref('')
let previouslyFocused: HTMLElement | null = null

const translationLocales = supportedLocales.filter((locale) => locale !== 'en')
const normalizedEnglishValue = computed(() => normalizeTagValue(englishValue.value))
const typeLabel = computed(() => {
  const labels: Record<EditableTagType, string> = {
    gender: 'Gender',
    topic: 'Topic',
    category: 'Category',
  }
  return props.type ? labels[props.type] : 'Tag'
})

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      await nextTick()
      previouslyFocused?.focus()
      return
    }
    previouslyFocused = document.activeElement as HTMLElement | null
    englishValue.value = canPrefillEnglish(props.initialEnglishValue)
      ? props.initialEnglishValue
      : ''
    translationValues.value = Object.fromEntries(
      translationLocales.map((language) => [language, '']),
    )
    validationMessage.value = ''
    await nextTick()
    englishInput.value?.focus()
  },
)

function normalizeTagValue(value: string): string {
  return value.normalize('NFKC').trim().replace(/\s+/g, '_')
}

function canPrefillEnglish(value: string): boolean {
  const normalized = normalizeTagValue(value)
  return /^(?=.*[A-Za-z0-9])[A-Za-z0-9_-]+$/.test(normalized)
}

function languageLabel(language: string): string {
  return language === 'zh-CN' ? t('Simplified Chinese') : language
}

function close(): void {
  if (!props.busy) emit('close')
}

function submit(): void {
  const normalizedEnglish = normalizedEnglishValue.value
  if (!/^(?=.*[A-Za-z0-9])[A-Za-z0-9_-]+$/.test(normalizedEnglish)) {
    validationMessage.value = t('Enter a valid English tag value')
    return
  }
  const translations = translationLocales.flatMap((language) => {
    const value = normalizeTagValue(translationValues.value[language] ?? '')
    return value ? [{ language, value }] : []
  })
  validationMessage.value = ''
  emit('submit', { englishValue: normalizedEnglish, translations })
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.stopPropagation()
    close()
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'input:not([disabled]), button:not([disabled])',
    ),
  )
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (!first || !last) return
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function handleDocumentKeydown(event: KeyboardEvent): void {
  if (props.open && event.key === 'Escape') close()
}

onMounted(() => document.addEventListener('keydown', handleDocumentKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', handleDocumentKeydown))
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
    role="presentation"
    @mousedown.self="close"
  >
    <form
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tag-dialog-title"
      class="w-full max-w-lg border border-line bg-surface p-5 shadow-lg"
      @submit.prevent="submit"
      @keydown="handleKeydown"
    >
      <h2 id="tag-dialog-title" class="text-lg font-semibold">
        {{ t('Create {type} tag', { type: t(typeLabel) }) }}
      </h2>

      <div class="mt-5 space-y-4">
        <div>
          <label for="tag-english-value" class="mb-1 block text-sm font-medium">
            {{ t('English value') }}
          </label>
          <input
            id="tag-english-value"
            ref="englishInput"
            v-model="englishValue"
            required
            maxlength="255"
            autocomplete="off"
            class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
          <TagChip
            v-if="normalizedEnglishValue"
            class="mt-2"
            :label="t('Saved value: {value}', { value: normalizedEnglishValue })"
          />
        </div>

        <div v-for="language in translationLocales" :key="language">
          <label :for="`tag-translation-${language}`" class="mb-1 block text-sm font-medium">
            {{ t('{language} (optional)', { language: languageLabel(language) }) }}
          </label>
          <input
            :id="`tag-translation-${language}`"
            v-model="translationValues[language]"
            maxlength="255"
            autocomplete="off"
            class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>
      </div>

      <p v-if="validationMessage || errorMessage" role="alert" class="mt-4 text-sm text-danger">
        {{ validationMessage || errorMessage }}
      </p>

      <div class="mt-6 flex flex-wrap justify-end gap-2 border-t border-line pt-5">
        <button
          type="button"
          class="h-9 border border-line px-3 text-sm font-medium hover:border-ink"
          @click="close"
        >
          {{ t('Cancel') }}
        </button>
        <button
          type="submit"
          :disabled="busy"
          class="h-9 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          {{ busy ? t('Creating') : t('Create and add') }}
        </button>
      </div>
    </form>
  </div>
</template>
