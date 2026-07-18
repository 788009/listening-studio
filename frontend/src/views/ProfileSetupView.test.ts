import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import ProfileSetupView from './ProfileSetupView.vue'
import { setLocale } from '@/i18n'

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
