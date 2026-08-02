import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { apiRequest } from '@/api/client'
import { ApiError } from '@/api/errors'
import {
  createDebugSession,
  endSession,
  getAuthenticationCapabilities,
  type AuthenticationCapabilities,
  type DebugSessionInput,
} from '@/api/auth'
import { usePreferencesStore } from '@/stores/preferences'

export interface CurrentUser {
  userId: string | null
  username: string | null
  suggestedUsername?: string | null
  locale: string
  profileComplete: boolean
  role: UserRole
}

export type UserRole = 'user' | 'admin' | 'super_admin'

export const useAuthStore = defineStore('auth', () => {
  const preferences = usePreferencesStore()
  const capabilities = ref<AuthenticationCapabilities>({
    loginMethod: 'none',
    loginUrl: null,
  })
  const capabilitiesLoaded = ref(false)
  const capabilitiesLoading = ref(false)
  const user = ref<CurrentUser | null>(null)
  const loaded = ref(false)
  const loading = ref(false)

  const isTeacher = computed(() => user.value !== null)
  const profileComplete = computed(() => user.value?.profileComplete ?? false)
  const isAdmin = computed(
    () => user.value?.role === 'admin' || user.value?.role === 'super_admin',
  )
  const isSuperAdmin = computed(() => user.value?.role === 'super_admin')

  async function loadCapabilities(): Promise<void> {
    if (capabilitiesLoaded.value || capabilitiesLoading.value) {
      return
    }
    capabilitiesLoading.value = true
    try {
      capabilities.value = await getAuthenticationCapabilities()
      capabilitiesLoaded.value = true
    } finally {
      capabilitiesLoading.value = false
    }
  }

  async function loadCurrentUser(): Promise<void> {
    if (loaded.value || loading.value) {
      return
    }
    loading.value = true
    try {
      user.value = await apiRequest<CurrentUser>('/users/me')
      preferences.setLanguage(user.value.locale)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        user.value = null
      } else {
        throw error
      }
    } finally {
      loaded.value = true
      loading.value = false
    }
  }

  function setCurrentUser(value: CurrentUser): void {
    user.value = value
    loaded.value = true
    preferences.setLanguage(value.locale)
  }

  async function signInDebug(input: DebugSessionInput): Promise<CurrentUser> {
    await createDebugSession(input)
    user.value = null
    loaded.value = false
    await loadCurrentUser()
    if (user.value === null) {
      throw new Error('The authenticated user could not be loaded')
    }
    return user.value
  }

  async function signOut(): Promise<string | null> {
    const result = await endSession()
    user.value = null
    loaded.value = true
    return result.redirectUrl
  }

  return {
    capabilities,
    capabilitiesLoaded,
    capabilitiesLoading,
    user,
    loaded,
    loading,
    isTeacher,
    profileComplete,
    isAdmin,
    isSuperAdmin,
    loadCapabilities,
    loadCurrentUser,
    setCurrentUser,
    signInDebug,
    signOut,
  }
})
