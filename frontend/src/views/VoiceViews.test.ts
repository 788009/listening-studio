import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import VoiceDetailView from './VoiceDetailView.vue'
import VoiceListView from './VoiceListView.vue'
import { useAuthStore, type UserRole } from '@/stores/auth'

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

function setupAuth(userId = 'TeacherOne', role: UserRole = 'user'): ReturnType<typeof createPinia> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setCurrentUser({
    userId,
    username: userId,
    locale: 'en',
    profileComplete: true,
    role,
  })
  return pinia
}

describe('voice views', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the responsive voice list with localized tag lines', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ items: [voice], page: 1, pageSize: 100, total: 1 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const pinia = setupAuth()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/voices', component: VoiceListView },
        { path: '/voices/create', component: { template: '<div />' } },
        { path: '/voice/:id', component: VoiceDetailView },
        { path: '/user/:userId', component: { template: '<div />' } },
      ],
    })
    await router.push('/voices?q=gender%3Afemale_voice')
    const wrapper = mount(VoiceListView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Clear English')
    expect(wrapper.text()).not.toContain('Author')
    expect(wrapper.text()).toContain('female voice')
    expect(wrapper.findAll('.tag-chip').length).toBeGreaterThan(0)
    expect(wrapper.get('#voice-search').element).toHaveProperty(
      'value',
      'gender:female_voice',
    )
    expect(fetchMock.mock.calls[0]?.[0]).toContain('q=gender%3Afemale_voice')
    expect(wrapper.get('a[href="/voice/7"]').attributes('href')).toBe('/voice/7')
    const authorLink = wrapper.get('a[href="/user/TeacherOne"]')
    expect(authorLink.text()).toBe('Teacher One')
    expect(authorLink.element.parentElement?.textContent).toContain('@TeacherOne')
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
        { path: '/user/:userId', component: { template: '<div />' } },
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
    expect(wrapper.text()).toContain('Author')
    const authorLink = wrapper.get('a[href="/user/TeacherOne"]')
    expect(authorLink.text()).toBe('Teacher One')
    expect(authorLink.element.parentElement?.textContent).toContain('@TeacherOne')
    expect(wrapper.findAll('dt').map((item) => item.text())).toEqual(
      expect.arrayContaining(['Author', 'Gender']),
    )
    const tagSearchLinks = wrapper
      .findAll('a')
      .filter((link) => link.attributes('href')?.includes('/voices?q='))
    expect(tagSearchLinks).toHaveLength(2)
    expect(
      tagSearchLinks.map((link) =>
        decodeURIComponent(link.attributes('href') ?? ''),
      ),
    ).toContain('/voices?q=gender:female_voice')
    const authorTag = tagSearchLinks.find((link) =>
      decodeURIComponent(link.attributes('href') ?? '').includes('author:TeacherOne'),
    )
    expect(authorTag?.text()).toContain('Teacher One')
    expect(authorTag?.text()).toContain('@TeacherOne')
    const useVoiceLink = wrapper.get('a[href="/create?voice=7"]')
    expect(useVoiceLink.text()).toBe('Use voice')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('#voice-visibility').exists()).toBe(true)
    expect(wrapper.findAll('dt').map((item) => item.text())).not.toContain('Visibility')
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

  it('lets an admin delete a public voice without exposing owner editing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ ...voice, visibility: 'public' })),
    )
    const pinia = setupAuth('VoiceAdmin', 'admin')
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
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('Edit')
    const deleteButton = wrapper.findAll('button').find((button) =>
      button.text().includes('Delete voice'),
    )
    expect(deleteButton).toBeDefined()
    await deleteButton?.trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('Delete voice')
  })

  it('edits gender tags while preserving the system author tag', async () => {
    const maleTag = {
      id: 3,
      type: 'gender',
      englishValue: 'male_voice',
      displayValue: 'male_voice',
      fullTag: 'gender:male_voice',
      translations: [],
    }
    let updateBody: { genderTagIds?: number[] } | undefined
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.startsWith('/api/voices/7?')) return Promise.resolve(jsonResponse(voice))
      if (path.startsWith('/api/audios?')) {
        return Promise.resolve(jsonResponse({ items: [], page: 1, pageSize: 100, total: 0 }))
      }
      if (path.startsWith('/api/voice-tags?')) {
        return Promise.resolve(jsonResponse([voice.tags[1], maleTag]))
      }
      if (path === '/api/voices/7' && init?.method === 'PATCH') {
        updateBody = JSON.parse(String(init.body))
        return Promise.resolve(jsonResponse({ ...voice, tags: [voice.tags[0], maleTag] }))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
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
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Edit')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('female voice')
    await wrapper.get('button[title="Remove tag"]').trigger('click')
    await wrapper.get('input[placeholder="Search tags"]').setValue('gender:male')
    await wrapper.get('[role="option"]').trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(updateBody?.genderTagIds).toEqual([3])
    expect(wrapper.text()).toContain('male voice')
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
