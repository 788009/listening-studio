import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter } from './index'
import { useAuthStore } from '@/stores/auth'


describe('profile completion guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('redirects a pending teacher to profile setup', async () => {
    const auth = useAuthStore()
    auth.setCurrentUser({
      userId: null,
      username: null,
      locale: 'en',
      profileComplete: false,
    })
    const router = createAppRouter(createMemoryHistory())

    await router.push('/create')

    expect(router.currentRoute.value.name).toBe('setup-profile')
  })

  it('allows a completed teacher to open a public user route', async () => {
    const auth = useAuthStore()
    auth.setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher One',
      locale: 'en',
      profileComplete: true,
    })
    const router = createAppRouter(createMemoryHistory())

    await router.push('/user/TeacherOne')

    expect(router.currentRoute.value.name).toBe('user')
  })
})
