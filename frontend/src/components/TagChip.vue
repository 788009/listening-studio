<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    label: string
    typeLabel?: string
    to?: RouteLocationRaw
    interactive?: boolean
    removable?: boolean
    selected?: boolean
    disabled?: boolean
  }>(),
  {
    typeLabel: undefined,
    to: undefined,
    interactive: false,
    removable: false,
    selected: false,
    disabled: false,
  },
)
const emit = defineEmits<{ activate: [] }>()
const { t } = useI18n()

const classes = computed(() => ({
  'tag-chip-selected': props.selected,
  'tag-chip-interactive': Boolean(props.to) || props.interactive || props.removable,
  'cursor-not-allowed opacity-50': props.disabled,
}))
const removeLabel = computed(() => t('Remove {tag}', { tag: props.label }))
const componentType = computed(() => {
  if (props.to) return RouterLink
  if (props.interactive || props.removable) return 'button'
  return 'span'
})
const componentProps = computed(() => {
  if (props.to) return { to: props.to }
  if (props.interactive || props.removable) {
    return {
      type: 'button',
      disabled: props.disabled,
      'aria-label': props.removable ? removeLabel.value : undefined,
      title: props.removable ? t('Remove tag') : undefined,
    }
  }
  return {}
})

function activate(): void {
  if (!props.to && (props.interactive || props.removable) && !props.disabled) {
    emit('activate')
  }
}
</script>

<template>
  <component
    :is="componentType"
    v-bind="componentProps"
    class="tag-chip"
    :class="classes"
    @click="activate"
  >
    <span v-if="typeLabel" class="tag-chip-type">{{ typeLabel }}</span>
    <span class="min-w-0 break-words">{{ label }}</span>
    <svg v-if="removable" viewBox="0 0 16 16" fill="none" class="h-3.5 w-3.5 shrink-0" aria-hidden="true">
      <path d="m4.5 4.5 7 7m0-7-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
    </svg>
  </component>
</template>
