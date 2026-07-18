import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import VoiceDetailView from './VoiceDetailView.vue'
import VoiceListView from './VoiceListView.vue'
import { useAuthStore } from '@/stores/auth'

const voice = {
  id: 7,
  author: { userId: 'TeacherOne', username: 'Teacher One' },
  title: 'Clear English',
  status: 'ready',
  visibility: 'private',
  sampleSource: 'original',
  tags: [
    {
      id: 1,
      type: 'author',
      englishValue: 'TeacherOne',
      displayValue: 'TeacherOne',
      fullTag: 'author:TeacherOne',
      translations: [],
    },
    {
      id: 2,
      type: 'gender',
      englishValue: 'female_voice',
      displayValue: 'female_voice',
      fullTag: 'gender:female_voice',
      translations: [],
    },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function setupAuth(): ReturnType<typeof createPinia> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setCurrentUser({
    userId: 'TeacherOne',
    username: 'Teacher One',
    locale: 'en',
    profileComplete: true,
  })
  return pinia
}

describe('voice views', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the responsive voice list with localized tag lines', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ items: [voice], page: 1, pageSize: 100, total: 1 }),
      ),
    )
    const pinia = setupAuth()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/voices', component: VoiceListView },
        { path: '/voices/create', component: { template: '<div />' } },
        { path: '/voice/:id', component: VoiceDetailView },
      ],
    })
    await router.push('/voices')
    const wrapper = mount(VoiceListView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Clear English')
    expect(wrapper.text()).toContain('female voice')
    expect(wrapper.get('a[href="/voice/7"]').attributes('href')).toBe('/voice/7')
  })

  it('renders untrusted titles as text instead of HTML', async () => {
    const unsafeTitle = '<img src=x onerror=alert(1)>'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [{ ...voice, title: unsafeTitle }],
          page: 1,
          pageSize: 100,
          total: 1,
        }),
      ),
    )
    const pinia = setupAuth()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/voices', component: VoiceListView },
        { path: '/voices/create', component: { template: '<div />' } },
        { path: '/voice/:id', component: VoiceDetailView },
      ],
    })
    await router.push('/voices')
    const wrapper = mount(VoiceListView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain(unsafeTitle)
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('shows owner controls, protected sample, and keyboard-accessible deletion', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(voice))
      .mockResolvedValueOnce(
        jsonResponse({ items: [], page: 1, pageSize: 100, total: 0 }),
      )
    vi.stubGlobal('fetch', fetchMock)
    const pinia = setupAuth()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/voice/:id', component: VoiceDetailView },
        { path: '/voices', component: VoiceListView, name: 'voices' },
        { path: '/create', component: { template: '<div />' }, name: 'create' },
        { path: '/user/:userId', component: { template: '<div />' } },
      ],
    })
    await router.push('/voice/7')
    const wrapper = mount(VoiceDetailView, {
      attachTo: document.body,
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    expect(wrapper.get('audio').attributes('src')).toBe('/media/voice/7/sample')
    const useVoiceLink = wrapper.get('a[href="/create?voice=7"]')
    expect(useVoiceLink.text()).toBe('Use voice')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const deleteButton = wrapper.findAll('button').find((button) =>
      button.text().includes('Delete voice'),
    )
    expect(deleteButton).toBeDefined()
    await deleteButton?.trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('Delete voice')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not render private content when the API returns not found', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: 'not_found',
              message: 'Resource not found',
              details: null,
              request_id: 'request-404',
            },
          },
          404,
        ),
      ),
    )
    const pinia = setupAuth()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/voice/:id', component: VoiceDetailView },
        { path: '/voices', component: VoiceListView },
      ],
    })
    await router.push('/voice/99')
    const wrapper = mount(VoiceDetailView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Resource not found')
    expect(wrapper.text()).not.toContain('Clear English')
  })
})
