<script setup lang="ts">
import { useI18n } from '@/i18n'

const props = defineProps<{
  title: string
  text: string
}>()

const { t } = useI18n()

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

async function copyText(): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(props.text)
      return
    } catch {
      // Use the document API when clipboard permission is unavailable.
    }
  }
  copyWithFallback(props.text)
}

function downloadText(): void {
  const blob = new Blob([props.text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${props.title.replace(/[\\/:*?"<>|]/g, '_') || 'transcript'}-transcript.txt`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="min-w-0">
    <div class="mb-4 flex flex-wrap justify-end gap-2">
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium hover:border-ink"
        @click="copyText"
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
        @click="downloadText"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Download') }}
      </button>
    </div>
    <pre class="overflow-x-auto border border-line bg-surface-alt p-4 text-sm leading-6"><code>{{ text }}</code></pre>
  </div>
</template>
