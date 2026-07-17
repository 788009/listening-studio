import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import AuthControls from './AuthControls.vue'
import { createAppRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'


describe('AuthControls', () => {
  afterEach(() => {
    document.cookie = 'listening_csrf=; Max-Age=0; Path=/'
    vi.unstubAllGlobals()
  })

  it('signs in a new debug identity and opens profile setup', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ loginMethod: 'debug', loginUrl: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            userId: null,
            username: null,
            locale: 'en',
            profileComplete: false,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
    vi.stubGlobal('fetch', fetchMock)
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().loaded = true
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    await router.isReady()
    const wrapper = mount(AuthControls, {
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    await wrapper.get('button').trigger('click')
    await wrapper.get('#debug-subject').setValue('teacher-001')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(fetchMock.mock.calls[1]?.[0]).toBe('/auth/debug/session')
    await vi.waitFor(() => {
      expect(router.currentRoute.value.name).toBe('setup-profile')
    })
    expect(useAuthStore().user?.profileComplete).toBe(false)
  })

  it('clears the local account through the CSRF-protected logout endpoint', async () => {
    document.cookie = 'listening_csrf=csrf-token; Path=/'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ redirectUrl: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.capabilitiesLoaded = true
    auth.setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher One',
      locale: 'en',
      profileComplete: true,
    })
    const router = createAppRouter(createMemoryHistory())
    await router.push('/user/TeacherOne')
    await router.isReady()
    const wrapper = mount(AuthControls, {
      global: { plugins: [pinia, router] },
    })

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/auth/session')
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-token')
    expect(auth.user).toBeNull()
    expect(router.currentRoute.value.name).toBe('library')
  })
})
