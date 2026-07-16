<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import {
  deleteAudio,
  listAudioTags,
  type AudioTag,
  type ResourceVisibility,
} from '@/api/audios'
import { ApiError } from '@/api/errors'
import {
  bulkUpdateManagedResources,
  listManagedResources,
  type BulkResourceUpdateResult,
  type ManagedResource,
  type ManagedResourceKind,
} from '@/api/resourceManagement'
import {
  deleteVoice,
  listVoiceGenderTags,
  type VoiceTag,
} from '@/api/voices'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ManagedResourceList from '@/components/ManagedResourceList.vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()

interface TagOption {
  id: number
  label: string
}

const PAGE_SIZE = 20
const tabs: { kind: ManagedResourceKind; label: string }[] = [
  { kind: 'voice', label: 'My voices' },
  { kind: 'audio', label: 'My audios' },
  { kind: 'generation_batch', label: 'Generation batches' },
  { kind: 'paper', label: 'Papers' },
]
const statuses: Record<ManagedResourceKind, string[]> = {
  voice: ['pending', 'processing', 'ready', 'failed'],
  audio: ['pending', 'processing', 'ready', 'failed'],
  generation_batch: ['pending', 'processing', 'completed', 'failed', 'cancelled'],
  paper: ['pending', 'processing', 'ready', 'failed'],
}

const kind = ref<ManagedResourceKind>('voice')
const items = ref<ManagedResource[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const errorMessage = ref('')
const query = ref('')
const status = ref('')
const visibility = ref<'' | ResourceVisibility>('')
const createdFrom = ref('')
const createdTo = ref('')
const tagOptions = ref<TagOption[]>([])
const filterTagIds = ref<number[]>([])
const selectedIds = ref<Set<number>>(new Set())
const bulkVisibility = ref<'' | ResourceVisibility>('')
const applyBulkTags = ref(false)
const bulkTagIds = ref<number[]>([])
const bulkBusy = ref(false)
const bulkResult = ref<BulkResourceUpdateResult | null>(null)
const deleteTarget = ref<ManagedResource | null>(null)
const deleting = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const supportsVisibility = computed(() => kind.value === 'voice' || kind.value === 'audio')
const supportsBulk = computed(() => supportsVisibility.value)
const allPageSelected = computed(
  () =>
    items.value.length > 0 &&
    items.value.every((item) => selectedIds.value.has(item.id)),
)

function statusLabel(value: string): string {
  return t(value.charAt(0).toUpperCase() + value.slice(1).replace('_', ' '))
}

function toggleTag(target: 'filter' | 'bulk', tagId: number): void {
  const source = target === 'filter' ? filterTagIds.value : bulkTagIds.value
  const next = source.includes(tagId)
    ? source.filter((id) => id !== tagId)
    : [...source, tagId]
  if (target === 'filter') filterTagIds.value = next
  else bulkTagIds.value = next
}

function toggleSelection(id: number): void {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
  bulkResult.value = null
}

function togglePageSelection(): void {
  const next = new Set(selectedIds.value)
  for (const item of items.value) {
    if (allPageSelected.value) next.delete(item.id)
    else next.add(item.id)
  }
  selectedIds.value = next
  bulkResult.value = null
}

async function loadResources(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await listManagedResources({
      kind: kind.value,
      page: page.value,
      pageSize: PAGE_SIZE,
      status: status.value || undefined,
      visibility: supportsVisibility.value ? visibility.value || undefined : undefined,
      tagIds: filterTagIds.value,
      createdFrom: dateStart(createdFrom.value),
      createdBefore: dateAfter(createdTo.value),
      query: query.value,
    })
    items.value = response.items
    total.value = response.total
  } catch (error) {
    items.value = []
    total.value = 0
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Resources could not be loaded')
  } finally {
    loading.value = false
  }
}

async function loadTags(): Promise<void> {
  try {
    let values: (VoiceTag | AudioTag)[] = []
    if (kind.value === 'voice') {
      values = await listVoiceGenderTags()
    } else if (kind.value === 'audio' || kind.value === 'generation_batch') {
      values = (await listAudioTags()).filter(
        (tag) =>
          tag.type !== 'author' &&
          (kind.value === 'audio' || tag.type === 'topic' || tag.type === 'category'),
      )
    }
    tagOptions.value = values.map((tag) => ({
      id: tag.id,
      label: `${statusLabel(tag.type)}: ${tag.displayValue.replace(/_/g, ' ')}`,
    }))
  } catch {
    tagOptions.value = []
  }
}

async function switchKind(value: ManagedResourceKind): Promise<void> {
  if (kind.value === value) return
  kind.value = value
  resetFilters()
  await Promise.all([loadTags(), loadResources()])
}

async function focusTab(index: number): Promise<void> {
  const normalized = (index + tabs.length) % tabs.length
  const tab = tabs[normalized]
  if (!tab) return
  await switchKind(tab.kind)
  await nextTick()
  document.getElementById(`resource-tab-${tab.kind}`)?.focus()
}

function handleTabKey(event: KeyboardEvent, index: number): void {
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    void focusTab(index + 1)
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    void focusTab(index - 1)
  } else if (event.key === 'Home') {
    event.preventDefault()
    void focusTab(0)
  } else if (event.key === 'End') {
    event.preventDefault()
    void focusTab(tabs.length - 1)
  }
}

function resetFilters(): void {
  page.value = 1
  query.value = ''
  status.value = ''
  visibility.value = ''
  createdFrom.value = ''
  createdTo.value = ''
  filterTagIds.value = []
  selectedIds.value = new Set()
  bulkVisibility.value = ''
  applyBulkTags.value = false
  bulkTagIds.value = []
  bulkResult.value = null
  errorMessage.value = ''
}

async function applyFilters(): Promise<void> {
  selectedIds.value = new Set()
  bulkResult.value = null
  page.value = 1
  await loadResources()
}

async function clearFilters(): Promise<void> {
  resetFilters()
  await loadResources()
}

async function movePage(target: number): Promise<void> {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  await loadResources()
}

async function applyBulkUpdate(): Promise<void> {
  if (!supportsBulk.value || selectedIds.value.size === 0 || bulkBusy.value) return
  if (!bulkVisibility.value && !applyBulkTags.value) {
    errorMessage.value = t('Select a visibility or tag change')
    return
  }
  bulkBusy.value = true
  errorMessage.value = ''
  bulkResult.value = null
  try {
    const resourceKind = kind.value === 'voice' ? 'voice' : 'audio'
    const result = await bulkUpdateManagedResources({
      kind: resourceKind,
      resourceIds: [...selectedIds.value],
      visibility: bulkVisibility.value || undefined,
      tagIds: applyBulkTags.value ? bulkTagIds.value : undefined,
    })
    bulkResult.value = result
    const succeeded = new Set(
      result.items
        .filter((item) => item.outcome === 'success')
        .map((item) => item.id),
    )
    selectedIds.value = new Set(
      [...selectedIds.value].filter((id) => !succeeded.has(id)),
    )
    await loadResources()
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Bulk update could not be completed')
  } finally {
    bulkBusy.value = false
  }
}

async function deleteResource(): Promise<void> {
  if (!deleteTarget.value || deleting.value) return
  deleting.value = true
  errorMessage.value = ''
  try {
    if (deleteTarget.value.kind === 'voice') {
      await deleteVoice(deleteTarget.value.id)
    } else if (deleteTarget.value.kind === 'audio') {
      await deleteAudio(deleteTarget.value.id)
    }
    const next = new Set(selectedIds.value)
    next.delete(deleteTarget.value.id)
    selectedIds.value = next
    deleteTarget.value = null
    await loadResources()
  } catch (error) {
    deleteTarget.value = null
    errorMessage.value =
      error instanceof ApiError ? error.message : t('Resource could not be deleted')
  } finally {
    deleting.value = false
  }
}

function dateStart(value: string): string | undefined {
  if (!value) return undefined
  return new Date(`${value}T00:00:00Z`).toISOString()
}

function dateAfter(value: string): string | undefined {
  if (!value) return undefined
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString()
}

onMounted(() => {
  void loadTags()
  void loadResources()
})
</script>

<template>
  <section aria-labelledby="management-title" class="min-w-0">
    <div class="border-b border-line pb-5">
      <p class="mb-1 text-sm font-medium text-accent">{{ t('Teacher workspace') }}</p>
      <h1 id="management-title" class="text-2xl font-semibold">{{ t('Resource management') }}</h1>
    </div>

    <div class="border-b border-line" role="tablist" :aria-label="t('Resource type')">
      <div class="grid grid-cols-2 sm:grid-cols-4">
        <button
          v-for="(tab, index) in tabs"
          :id="`resource-tab-${tab.kind}`"
          :key="tab.kind"
          type="button"
          role="tab"
          :aria-selected="kind === tab.kind"
          :tabindex="kind === tab.kind ? 0 : -1"
          class="h-11 border-b-2 px-4 text-sm font-medium"
          :class="kind === tab.kind ? 'border-accent text-ink' : 'border-transparent text-muted hover:text-ink'"
          @click="switchKind(tab.kind)"
          @keydown="handleTabKey($event, index)"
        >
          {{ t(tab.label) }}
        </button>
      </div>
    </div>

    <p
      v-if="errorMessage"
      role="alert"
      class="border-b border-line bg-surface px-4 py-4 text-sm text-danger"
    >
      {{ errorMessage }}
    </p>

    <form class="border-b border-line bg-surface px-4 py-5" @submit.prevent="applyFilters">
      <div class="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(12rem,1fr)_10rem_10rem_10rem_10rem]">
        <div class="min-w-0">
          <label for="management-query" class="mb-1 block text-sm font-medium">{{ t('Title') }}</label>
          <input
            id="management-query"
            v-model="query"
            type="search"
            maxlength="200"
            class="h-10 w-full border border-line px-3 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          />
        </div>
        <div>
          <label for="management-status" class="mb-1 block text-sm font-medium">{{ t('Status') }}</label>
          <select
            id="management-status"
            v-model="status"
            class="h-10 w-full border border-line bg-surface px-3 text-sm"
          >
            <option value="">{{ t('All') }}</option>
            <option v-for="value in statuses[kind]" :key="value" :value="value">
              {{ statusLabel(value) }}
            </option>
          </select>
        </div>
        <div v-if="supportsVisibility">
          <label for="management-visibility" class="mb-1 block text-sm font-medium">{{ t('Visibility') }}</label>
          <select
            id="management-visibility"
            v-model="visibility"
            class="h-10 w-full border border-line bg-surface px-3 text-sm"
          >
            <option value="">{{ t('All') }}</option>
            <option value="private">{{ t('Private') }}</option>
            <option value="public">{{ t('Public') }}</option>
          </select>
        </div>
        <div>
          <label for="management-created-from" class="mb-1 block text-sm font-medium">{{ t('Created from') }}</label>
          <input
            id="management-created-from"
            v-model="createdFrom"
            type="date"
            class="h-10 w-full border border-line px-2 text-sm"
          />
        </div>
        <div>
          <label for="management-created-to" class="mb-1 block text-sm font-medium">{{ t('Created to') }}</label>
          <input
            id="management-created-to"
            v-model="createdTo"
            type="date"
            class="h-10 w-full border border-line px-2 text-sm"
          />
        </div>
      </div>

      <fieldset v-if="tagOptions.length > 0" class="mt-4 border-t border-line pt-4">
        <legend class="mb-2 text-sm font-medium">{{ t('Tags') }}</legend>
        <div class="flex flex-wrap gap-x-5 gap-y-2">
          <label
            v-for="tag in tagOptions"
            :key="tag.id"
            class="flex min-w-0 max-w-full items-start gap-2 text-sm"
          >
            <input
              type="checkbox"
              class="mt-0.5 h-4 w-4 shrink-0 accent-accent"
              :checked="filterTagIds.includes(tag.id)"
              @change="toggleTag('filter', tag.id)"
            />
            <span class="min-w-0 break-all">{{ tag.label }}</span>
          </label>
        </div>
      </fieldset>

      <div class="mt-5 flex flex-wrap justify-end gap-2 border-t border-line pt-4">
        <button
          type="button"
          class="h-9 border border-line px-3 text-sm font-medium hover:border-ink"
          @click="clearFilters"
        >
          {{ t('Clear') }}
        </button>
        <button
          type="submit"
          :disabled="loading"
          class="h-9 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
        >
          {{ t('Apply filters') }}
        </button>
      </div>
    </form>

    <div
      v-if="supportsBulk && selectedIds.size > 0"
      class="border-b border-line bg-surface px-4 py-5"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-sm font-semibold">
          {{ t('{count} selected across pages', { count: selectedIds.size }) }}
        </h2>
        <button
          type="button"
          class="text-sm font-medium text-muted hover:text-ink hover:underline"
          @click="selectedIds = new Set()"
        >
          {{ t('Clear selection') }}
        </button>
      </div>
      <div class="mt-4 grid min-w-0 gap-5 lg:grid-cols-[12rem_minmax(0,1fr)_10rem] lg:items-end">
        <div>
          <label for="bulk-visibility" class="mb-1 block text-sm font-medium">{{ t('Visibility change') }}</label>
          <select
            id="bulk-visibility"
            v-model="bulkVisibility"
            class="h-10 w-full border border-line bg-surface px-3 text-sm"
          >
            <option value="">{{ t('No change') }}</option>
            <option value="private">{{ t('Private') }}</option>
            <option value="public">{{ t('Public') }}</option>
          </select>
        </div>
        <fieldset class="min-w-0">
          <label class="flex items-center gap-2 text-sm font-medium">
            <input v-model="applyBulkTags" type="checkbox" class="h-4 w-4 accent-accent" />
            {{ t('Replace tags') }}
          </label>
          <div v-if="applyBulkTags" class="mt-2 flex flex-wrap gap-x-4 gap-y-2">
            <label v-for="tag in tagOptions" :key="tag.id" class="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                class="mt-0.5 h-4 w-4 accent-accent"
                :checked="bulkTagIds.includes(tag.id)"
                @change="toggleTag('bulk', tag.id)"
              />
              {{ tag.label }}
            </label>
            <span v-if="tagOptions.length === 0" class="text-sm text-muted">{{ t('No user tags') }}</span>
          </div>
        </fieldset>
        <button
          type="button"
          :disabled="bulkBusy"
          class="h-10 bg-ink px-4 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
          @click="applyBulkUpdate"
        >
          {{ bulkBusy ? t('Applying') : t('Apply changes') }}
        </button>
      </div>
    </div>

    <div v-if="bulkResult" class="border-b border-line bg-surface px-4 py-5" aria-live="polite">
      <p class="text-sm font-medium">
        {{ t('{success} succeeded, {conflict} conflicts, {failed} failed', {
          success: bulkResult.successCount,
          conflict: bulkResult.conflictCount,
          failed: bulkResult.failedCount,
        }) }}
      </p>
      <ul class="mt-3 space-y-1 text-sm">
        <li
          v-for="result in bulkResult.items"
          :key="result.id"
          :class="result.outcome === 'success' ? 'text-success' : 'text-danger'"
        >
          {{ result.id }}: {{ result.message }}
        </li>
      </ul>
    </div>

    <div class="flex flex-wrap items-center justify-between gap-4 border-b border-line py-4">
      <div class="flex items-center gap-3">
        <label v-if="supportsBulk && items.length > 0" class="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            class="h-4 w-4 accent-accent"
            :checked="allPageSelected"
            :disabled="loading"
            @change="togglePageSelection"
          />
          {{ t('Select page') }}
        </label>
        <span class="text-sm text-muted">{{ t('{count} resources', { count: total }) }}</span>
      </div>
      <span class="text-sm tabular-nums text-muted">
        {{ t('Page {page} of {total}', { page, total: totalPages }) }}
      </span>
    </div>

    <p v-if="loading" class="border-b border-line py-12 text-sm text-muted">{{ t('Loading resources') }}</p>
    <p v-else-if="items.length === 0" class="border-b border-line py-12 text-sm text-muted">
      {{ t('No resources found') }}
    </p>
    <ManagedResourceList
      v-else
      :items="items"
      :selectable="supportsBulk"
      :selected-ids="selectedIds"
      :busy="bulkBusy || deleting"
      @select="toggleSelection"
      @delete="deleteTarget = $event"
    />

    <nav
      v-if="!loading && totalPages > 1"
      class="flex items-center justify-between gap-4 border-b border-line py-4"
      :aria-label="t('Resource pages')"
    >
      <button
        type="button"
        :disabled="page === 1"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium disabled:opacity-50"
        @click="movePage(page - 1)"
      >
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" />
        </svg>
        {{ t('Previous') }}
      </button>
      <span class="text-sm tabular-nums text-muted">{{ page }} / {{ totalPages }}</span>
      <button
        type="button"
        :disabled="page === totalPages"
        class="inline-flex h-9 items-center gap-2 border border-line px-3 text-sm font-medium disabled:opacity-50"
        @click="movePage(page + 1)"
      >
        {{ t('Next') }}
        <svg viewBox="0 0 24 24" fill="none" class="h-4 w-4" aria-hidden="true">
          <path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" />
        </svg>
      </button>
    </nav>

    <ConfirmDialog
      :open="deleteTarget !== null"
      :title="t('Delete {title}', { title: deleteTarget?.title ?? t('Resource') })"
      :busy="deleting"
      confirm-label="Delete"
      @close="deleteTarget = null"
      @confirm="deleteResource"
    >
      <p>{{ t('The resource record and stored files will be removed.') }}</p>
    </ConfirmDialog>
  </section>
</template>
