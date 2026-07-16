<script setup lang="ts">
import { useI18n } from '@/i18n'

const { t } = useI18n()
defineProps<{ modelValue: 'single' | 'dialogue' }>()
const emit = defineEmits<{
  'update:modelValue': [value: 'single' | 'dialogue']
}>()
</script>

<template>
  <div class="grid h-10 grid-cols-2 border border-line" :aria-label="t('Creation mode')">
    <button
      type="button"
      :aria-pressed="modelValue === 'single'"
      :class="modelValue === 'single' ? 'bg-ink text-white' : 'bg-surface text-ink hover:bg-canvas'"
      class="min-w-0 px-3 text-sm font-medium"
      @click="emit('update:modelValue', 'single')"
    >
      {{ t('Single') }}
    </button>
    <button
      type="button"
      :aria-pressed="modelValue === 'dialogue'"
      :class="modelValue === 'dialogue' ? 'bg-ink text-white' : 'bg-surface text-ink hover:bg-canvas'"
      class="min-w-0 border-l border-line px-3 text-sm font-medium"
      @click="emit('update:modelValue', 'dialogue')"
    >
      {{ t('Dialogue') }}
    </button>
  </div>
</template>
