<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'

import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    busy?: boolean
    confirmLabel?: string
  }>(),
  { busy: false, confirmLabel: 'Confirm' },
)
const emit = defineEmits<{ close: []; confirm: [] }>()
const { t } = useI18n()
const titleId = useId()
const dialog = ref<HTMLElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
let previouslyFocused: HTMLElement | null = null

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previouslyFocused = document.activeElement as HTMLElement | null
      await nextTick()
      cancelButton.value?.focus()
    } else {
      await nextTick()
      previouslyFocused?.focus()
    }
  },
)

function close(): void {
  if (!props.busy) emit('close')
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    close()
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = Array.from(
    dialog.value.querySelectorAll<HTMLElement>('button:not([disabled])'),
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
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      class="w-full max-w-md border border-line bg-surface p-5 shadow-lg"
      @keydown="handleKeydown"
    >
      <h2 :id="titleId" class="text-lg font-semibold">{{ title }}</h2>
      <div class="mt-2 text-sm text-muted"><slot /></div>
      <div class="mt-6 flex flex-wrap justify-end gap-2">
        <button
          ref="cancelButton"
          type="button"
          class="h-9 border border-line px-3 text-sm font-medium hover:border-ink"
          @click="close"
        >
          {{ t('Cancel') }}
        </button>
        <button
          type="button"
          :disabled="busy"
          class="h-9 bg-danger px-3 text-sm font-medium text-white disabled:opacity-60"
          @click="emit('confirm')"
        >
          {{ busy ? t('Working') : t(confirmLabel) }}
        </button>
      </div>
    </div>
  </div>
</template>
