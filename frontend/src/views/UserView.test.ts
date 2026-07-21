import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { setLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import UserView from './UserView.vue'

const profile = {
  userId: 'TeacherOne',
  username: 'Teacher One',
  locale: 'en',
  createdAt: '2026-07-19T00:00:00Z',
  statistics: {
    publicVoiceCount: 2,
    publicAudioCount: 1,
  },
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function mountUserView(authenticated: boolean) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(profile)))
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  if (authenticated) {
    auth.setCurrentUser({
      userId: 'OtherTeacher',
      username: 'Other Teacher',
      locale: 'en',
      profileComplete: true,
      role: 'user',
    })
  } else {
    auth.loaded = true
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/user/:userId', component: UserView },
      { path: '/audio', component: { template: '<div />' } },
      { path: '/voices', component: { template: '<div />' } },
    ],
  })
  await router.push('/user/TeacherOne')
  const wrapper = mount(UserView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

describe('user view', () => {
  afterEach(() => {
    setLocale('en')
    vi.unstubAllGlobals()
  })

  it('shows only public audio information to anonymous visitors', async () => {
    const { wrapper, router } = await mountUserView(false)
    const statistics = wrapper.findAll('dl > div')

    expect(statistics).toHaveLength(1)
    expect(statistics[0]?.get('dt').text()).toBe('Public audio count')
    expect(statistics[0]?.get('dd').text()).toBe('1')
    expect(statistics[0]?.attributes('role')).toBe('link')
    await statistics[0]?.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/audio')
    expect(router.currentRoute.value.query.q).toBe('author:TeacherOne')
  })

  it('shows public voice and audio information to signed-in teachers', async () => {
    const { wrapper, router } = await mountUserView(true)
    const statistics = wrapper.findAll('dl > div')

    expect(statistics).toHaveLength(2)
    expect(statistics[0]?.get('dt').text()).toBe('Public voices')
    expect(statistics[0]?.get('dd').text()).toBe('2')
    expect(statistics[1]?.get('dt').text()).toBe('Public audio count')
    expect(statistics[1]?.get('dd').text()).toBe('1')
    expect(statistics[0]?.attributes('tabindex')).toBe('0')
    await statistics[0]?.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/voices')
    expect(router.currentRoute.value.query.q).toBe('author:TeacherOne')
  })
})
