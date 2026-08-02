import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setLocale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import LanguageSelect from './LanguageSelect.vue'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(): Response {
  return new Response(
    JSON.stringify({
      error: {
        code: 'internal_error',
        message: 'Language could not be updated',
        details: null,
        request_id: 'language-request',
      },
    }),
    { status: 500, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('LanguageSelect', () => {
  beforeEach(() => {
    localStorage.clear()
    setLocale('en')
  })

  afterEach(() => {
    setLocale('en')
    vi.unstubAllGlobals()
  })

  it('changes and persists the language for an anonymous visitor', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const pinia = createPinia()
    useAuthStore(pinia).loaded = true
    const wrapper = mount(LanguageSelect, { global: { plugins: [pinia] } })

    await wrapper.get('select').setValue('zh-CN')

    expect(document.documentElement.lang).toBe('zh-CN')
    expect(localStorage.getItem('listening-studio-language')).toBe('zh-CN')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('updates the saved preference for a signed-in user', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        userId: 'TeacherOne',
        username: 'Teacher One',
        locale: 'zh-CN',
        profileComplete: true,
        role: 'user',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher One',
      locale: 'en',
      profileComplete: true,
      role: 'user',
    })
    const wrapper = mount(LanguageSelect, { global: { plugins: [pinia] } })

    await wrapper.get('select').setValue('zh-CN')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/users/me/profile',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ locale: 'zh-CN' }),
      }),
    )
    expect(auth.user?.locale).toBe('zh-CN')
  })

  it('restores the previous language when the saved preference cannot be updated', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse()))
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher One',
      locale: 'en',
      profileComplete: true,
      role: 'user',
    })
    const wrapper = mount(LanguageSelect, { global: { plugins: [pinia] } })

    await wrapper.get('select').setValue('zh-CN')
    await flushPromises()

    expect(document.documentElement.lang).toBe('en')
    expect(wrapper.get('[role="alert"]').text()).toBe('Language update failed')
  })
})
