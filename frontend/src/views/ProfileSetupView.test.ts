import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import ProfileSetupView from './ProfileSetupView.vue'
import { setLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

function errorResponse(code: string, message: string): Response {
  return new Response(
    JSON.stringify({
      error: {
        code,
        message,
        details: { field: 'userId' },
        request_id: 'profile-request',
      },
    }),
    { status: 409, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('profile setup view', () => {
  afterEach(() => {
    setLocale('en')
    vi.unstubAllGlobals()
  })

  it('prefills an editable display name from the OIDC identity', async () => {
    const pinia = createPinia()
    useAuthStore(pinia).setCurrentUser({
      userId: null,
      username: null,
      suggestedUsername: 'Teacher One',
      locale: 'en',
      profileComplete: false,
      role: 'user',
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/setup-profile', component: ProfileSetupView }],
    })
    await router.push('/setup-profile')

    const wrapper = mount(ProfileSetupView, {
      global: { plugins: [pinia, router] },
    })
    const usernameInput = wrapper.get<HTMLInputElement>('#username')

    expect(usernameInput.element.value).toBe('Teacher One')
    await usernameInput.setValue('Preferred Name')
    expect(usernameInput.element.value).toBe('Preferred Name')
  })

  it('explains when the requested user ID is already occupied', async () => {
    setLocale('zh-CN')
    const fetchMock = vi.fn().mockResolvedValue(
      errorResponse(
        'user_id_taken',
        'This user ID is already in use. Choose another ID.',
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/setup-profile', component: ProfileSetupView },
        { path: '/user/:userId', component: { template: '<div />' } },
      ],
    })
    await router.push('/setup-profile')

    const wrapper = mount(ProfileSetupView, {
      global: { plugins: [createPinia(), router] },
    })
    await wrapper.get('#user-id').setValue('TeacherOne')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/users/me/profile')
    expect(wrapper.get('[role="alert"]').text()).toBe(
      '该用户 ID 已被占用，请选择其他 ID',
    )
    expect(wrapper.get('#user-id').attributes('aria-invalid')).toBe('true')
    expect(wrapper.get('#user-id').attributes('aria-describedby')).toBe('user-id-error')

    await wrapper.get('#user-id').setValue('TeacherTwo')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
