<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  listManagedUsers,
  updateManagedUserRole,
  type AssignableUserRole,
  type ManagedUser,
} from '@/api/users'
import { ApiError } from '@/api/errors'
import { useI18n } from '@/i18n'

const { locale, t } = useI18n()
const users = ref<ManagedUser[]>([])
const page = ref(1)
const pageSize = 25
const total = ref(0)
const loading = ref(true)
const updatingUserId = ref<string | null>(null)
const errorMessage = ref('')
const roleDrafts = ref<Record<string, AssignableUserRole>>({})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function roleLabel(role: ManagedUser['role']): string {
  if (role === 'super_admin') return t('Super Admin')
  if (role === 'admin') return t('Admin')
  return t('User')
}

function formattedDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(value))
}

async function loadUsers(targetPage = page.value): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await listManagedUsers(targetPage, pageSize)
    users.value = result.items
    page.value = result.page
    total.value = result.total
    roleDrafts.value = Object.fromEntries(
      result.items
        .filter((user) => user.role !== 'super_admin')
        .map((user) => [user.userId, user.role as AssignableUserRole]),
    )
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : t('Users could not be loaded')
  } finally {
    loading.value = false
  }
}

async function saveRole(user: ManagedUser): Promise<void> {
  const role = roleDrafts.value[user.userId]
  if (!role || role === user.role || updatingUserId.value !== null) return
  updatingUserId.value = user.userId
  errorMessage.value = ''
  try {
    const updated = await updateManagedUserRole(user.userId, role)
    users.value = users.value.map((item) => (item.userId === updated.userId ? updated : item))
    roleDrafts.value[updated.userId] = updated.role as AssignableUserRole
  } catch (error) {
    roleDrafts.value[user.userId] = user.role as AssignableUserRole
    errorMessage.value = error instanceof ApiError ? error.message : t('Role could not be updated')
  } finally {
    updatingUserId.value = null
  }
}

onMounted(() => loadUsers())
</script>

<template>
  <section class="page-shell" aria-labelledby="user-roles-title">
    <div class="page-heading">
      <div>
        <p class="mb-2 text-sm font-medium text-muted">{{ t('Administration') }}</p>
        <h1 id="user-roles-title" class="text-3xl font-semibold">{{ t('User roles') }}</h1>
      </div>
      <p class="text-sm text-muted">{{ t('{count} users', { count: total }) }}</p>
    </div>

    <p v-if="errorMessage" role="alert" class="border-b border-line py-4 text-sm text-danger">
      {{ errorMessage }}
    </p>
    <p v-if="loading" class="border-b border-line py-10 text-sm text-muted">
      {{ t('Loading users') }}
    </p>

    <div v-else class="mt-6 border-t border-line">
      <div class="hidden grid-cols-[minmax(0,1fr)_10rem_18rem] gap-5 border-b border-line px-3 py-2 text-xs font-medium text-muted md:grid">
        <span>{{ t('Teacher account') }}</span>
        <span>{{ t('Created') }}</span>
        <span>{{ t('Role') }}</span>
      </div>
      <div
        v-for="user in users"
        :key="user.userId"
        class="grid gap-4 border-b border-line px-3 py-4 md:grid-cols-[minmax(0,1fr)_10rem_18rem] md:items-center md:gap-5"
      >
        <div class="min-w-0">
          <p class="truncate text-sm font-medium">{{ user.username || user.userId }}</p>
          <p class="truncate text-xs text-muted">{{ user.userId }}</p>
        </div>
        <p class="text-sm text-muted">{{ formattedDate(user.createdAt) }}</p>
        <div v-if="user.role === 'super_admin'" class="text-sm font-medium">
          {{ roleLabel(user.role) }}
        </div>
        <div v-else class="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
          <select
            v-model="roleDrafts[user.userId]"
            :aria-label="t('Role for {userId}', { userId: user.userId })"
            class="h-9 min-w-0 border border-line bg-surface px-2 text-sm focus:border-accent focus:outline-none focus:shadow-focus"
          >
            <option value="user">{{ t('User') }}</option>
            <option value="admin">{{ t('Admin') }}</option>
          </select>
          <button
            type="button"
            :disabled="roleDrafts[user.userId] === user.role || updatingUserId !== null"
            class="h-9 bg-ink px-3 text-sm font-medium text-white hover:bg-accent disabled:opacity-50"
            @click="saveRole(user)"
          >
            {{ updatingUserId === user.userId ? t('Saving') : t('Save') }}
          </button>
        </div>
      </div>
      <p v-if="users.length === 0" class="border-b border-line py-10 text-sm text-muted">
        {{ t('No users found') }}
      </p>
    </div>

    <nav v-if="!loading && totalPages > 1" :aria-label="t('User pages')" class="mt-6 flex items-center justify-between gap-4">
      <button
        type="button"
        :disabled="page <= 1"
        class="h-9 border border-line px-3 text-sm font-medium hover:border-ink disabled:opacity-40"
        @click="loadUsers(page - 1)"
      >
        {{ t('Previous') }}
      </button>
      <span class="text-sm text-muted">{{ t('Page {page} of {total}', { page, total: totalPages }) }}</span>
      <button
        type="button"
        :disabled="page >= totalPages"
        class="h-9 border border-line px-3 text-sm font-medium hover:border-ink disabled:opacity-40"
        @click="loadUsers(page + 1)"
      >
        {{ t('Next') }}
      </button>
    </nav>
  </section>
</template>
