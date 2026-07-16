import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { apiRequest } from '@/api/client'
import { ApiError } from '@/api/errors'


export interface CurrentUser {
  userId: string | null
  username: string | null
  locale: string
  profileComplete: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  const loaded = ref(false)
  const loading = ref(false)

  const isTeacher = computed(() => user.value !== null)
  const profileComplete = computed(() => user.value?.profileComplete ?? false)

  async function loadCurrentUser(): Promise<void> {
    if (loaded.value || loading.value) {
      return
    }
    loading.value = true
    try {
      user.value = await apiRequest<CurrentUser>('/users/me')
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
  }

  return {
    user,
    loaded,
    loading,
    isTeacher,
    profileComplete,
    loadCurrentUser,
    setCurrentUser,
  }
})
