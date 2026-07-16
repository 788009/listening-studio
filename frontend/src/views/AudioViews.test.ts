import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import type { Audio } from '@/api/audios'
import AudioSearchBox from '@/components/AudioSearchBox.vue'
import { useAuthStore } from '@/stores/auth'
import AudioDetailView from './AudioDetailView.vue'
import LibraryView from './LibraryView.vue'

const audio: Audio = {
  id: 5,
  author: { userId: 'TeacherOne', username: 'Teacher One' },
  title: 'Climate briefing',
  text: 'A readable listening transcript.',
  sourceType: 'multi_turn',
  status: 'ready',
  visibility: 'public',
  durationSeconds: 65,
  sampleRate: 24000,
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
      type: 'topic',
      englishValue: 'climate_change',
      displayValue: '气候_变化',
      fullTag: 'topic:climate_change',
      translations: [{ language: 'zh-CN', value: '气候_变化' }],
    },
  ],
  utterances: [
    { voiceId: 1, speakerDisplayName: 'Teacher', text: 'First line', position: 0 },
    { voiceId: 2, speakerDisplayName: 'Student', text: 'Second line', position: 1 },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function setupAuth(owner = false): ReturnType<typeof createPinia> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  if (owner) {
    auth.setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher One',
      locale: 'en',
      profileComplete: true,
    })
  } else {
    auth.loaded = true
  }
  return pinia
}

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: LibraryView, name: 'library' },
      { path: '/audio/:id', component: AudioDetailView },
      { path: '/user/:userId', component: { template: '<div />' } },
    ],
  })
}

describe('audio views', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('lets a student browse and play public audio without management controls', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = String(input)
      if (path.startsWith('/api/audio-tags')) return Promise.resolve(jsonResponse(audio.tags))
      return Promise.resolve(
        jsonResponse({ items: [audio], page: 1, pageSize: 20, total: 1 }),
      )
    })
    vi.stubGlobal(
      'fetch',
      fetchMock,
    )
    const pinia = setupAuth()
    const router = testRouter()
    await router.push('/')
    const wrapper = mount(LibraryView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Climate briefing')
    expect(wrapper.get('audio').attributes('src')).toBe('/media/audio/5')
    expect(wrapper.find('button').text()).toContain('Search')
    expect(wrapper.text()).not.toContain('Delete audio')
  })

  it('shows localized suggestions but inserts the English full tag', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(['topic:climate_change'])),
    )
    const wrapper = mount(AudioSearchBox, {
      props: { modelValue: '', tags: audio.tags, busy: false },
    })

    await wrapper.setProps({ modelValue: 'clim' })
    await vi.advanceTimersByTimeAsync(160)
    await flushPromises()
    expect(wrapper.text()).toContain('Topic: 气候 变化')
    await wrapper.get('input').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]?.[0]).toBe('topic:climate_change ')
  })

  it('renders public detail text, speakers, tags, and playback for a student', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(audio)))
    const pinia = setupAuth()
    const router = testRouter()
    await router.push('/audio/5')
    const wrapper = mount(AudioDetailView, {
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('A readable listening transcript.')
    expect(wrapper.text()).toContain('Second line')
    expect(wrapper.text()).toContain('气候 变化')
    expect(wrapper.get('audio').attributes('src')).toBe('/media/audio/5')
    expect(wrapper.text()).not.toContain('Edit')
  })

  it('shows edit and keyboard-accessible deletion only to the owner', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(audio)))
    const pinia = setupAuth(true)
    const router = testRouter()
    await router.push('/audio/5')
    const wrapper = mount(AudioDetailView, {
      attachTo: document.body,
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    await wrapper.get('button').trigger('click')
    const deleteButton = wrapper.findAll('button').find((button) =>
      button.text().includes('Delete audio'),
    )
    await deleteButton?.trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('Delete audio')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not render private audio content after a not-found response', async () => {
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
    const router = testRouter()
    await router.push('/audio/99')
    const wrapper = mount(AudioDetailView, {
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Resource not found')
    expect(wrapper.text()).not.toContain('A readable listening transcript.')
    expect(wrapper.find('audio').exists()).toBe(false)
  })
})
