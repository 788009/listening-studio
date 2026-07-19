import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import type { Audio } from '@/api/audios'
import AudioSearchBox from '@/components/AudioSearchBox.vue'
import { setLocale } from '@/i18n'
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
    {
      voiceId: 1,
      voiceTitle: 'test',
      voiceTag: 'voice:test',
      speakerDisplayName: 'Woman',
      text: 'First line',
      position: 0,
    },
    {
      voiceId: 2,
      voiceTitle: 'Second voice',
      voiceTag: 'voice:Second_voice',
      speakerDisplayName: 'Student',
      text: 'Second line',
      position: 1,
    },
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
      { path: '/audio', component: LibraryView, name: 'library' },
      { path: '/audio/:id', component: AudioDetailView },
      { path: '/user/:userId', component: { template: '<div />' } },
    ],
  })
}

describe('audio views', () => {
  afterEach(() => {
    setLocale('en')
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
    await router.push('/audio?q=topic%3Aclimate_change')
    const wrapper = mount(LibraryView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Climate briefing')
    expect(wrapper.text()).not.toContain('Author')
    expect(wrapper.text()).not.toContain('Speaker')
    expect(wrapper.text()).not.toContain('Woman')
    expect(wrapper.text()).not.toContain('Student')
    expect(wrapper.text()).toContain('Voice')
    expect(wrapper.text()).toContain('Second voice')
    expect(
      wrapper
        .findAll('a')
        .map((link) => decodeURIComponent(link.attributes('href') ?? '')),
    ).toContain('/audio?q=voice:test')
    expect(wrapper.findAll('.tag-chip').length).toBeGreaterThanOrEqual(3)
    expect(wrapper.get('input[role="combobox"]').element).toHaveProperty(
      'value',
      'topic:climate_change',
    )
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('q=topic%3Aclimate_change'),
      ),
    ).toBe(true)
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('visibility=public'),
      ),
    ).toBe(false)
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
    expect(wrapper.find('.tag-chip').exists()).toBe(false)
    await wrapper.get('input').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    const updates = wrapper.emitted('update:modelValue') ?? []
    expect(updates[updates.length - 1]?.[0]).toBe('topic:climate_change ')
  })

  it('keeps the latest suggestions when an older request finishes later', async () => {
    vi.useFakeTimers()
    let resolveFirst!: (response: Response) => void
    const firstResponse = new Promise<Response>((resolve) => {
      resolveFirst = resolve
    })
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const query = new URL(String(input), 'http://test').searchParams.get('q')
      return query === 's'
        ? firstResponse
        : Promise.resolve(jsonResponse(['category:single']))
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(AudioSearchBox, {
      props: { modelValue: '', tags: [], busy: false },
    })

    await wrapper.setProps({ modelValue: 's' })
    await vi.advanceTimersByTimeAsync(160)
    await wrapper.setProps({ modelValue: 'si' })
    await vi.advanceTimersByTimeAsync(160)
    await flushPromises()
    expect(wrapper.text()).toContain('category:single')

    resolveFirst(jsonResponse(['category:conversation']))
    await flushPromises()
    expect(wrapper.text()).toContain('category:single')
    expect(wrapper.text()).not.toContain('category:conversation')
  })

  it('does not suggest a tag already present in the search query', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(['topic:climate_change', 'topic:climate_policy']),
      ),
    )
    const wrapper = mount(AudioSearchBox, {
      props: { modelValue: '', tags: audio.tags, busy: false },
    })

    await wrapper.setProps({ modelValue: 'topic:climate_change clim' })
    await vi.advanceTimersByTimeAsync(160)
    await flushPromises()

    const options = wrapper.findAll('[role="option"]')
    expect(options).toHaveLength(1)
    expect(options[0]?.text()).toContain('topic:climate policy')
  })

  it('switches fixed text and tag display without changing canonical values or IDs', async () => {
    setLocale('zh-CN')
    const fallbackTag = {
      ...audio.tags[1]!,
      id: 3,
      englishValue: 'environment',
      displayValue: 'environment',
      fullTag: 'topic:environment',
      translations: [],
    }
    const localizedAudio = { ...audio, tags: [...audio.tags, fallbackTag] }
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = String(input)
      if (path.startsWith('/api/audio-tags')) {
        return Promise.resolve(jsonResponse(localizedAudio.tags))
      }
      return Promise.resolve(
        jsonResponse({ items: [localizedAudio], page: 1, pageSize: 20, total: 1 }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    const pinia = setupAuth()
    const router = testRouter()
    await router.push('/audio')
    const wrapper = mount(LibraryView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('听力资源库')
    expect(wrapper.text()).toContain('气候 变化')
    expect(wrapper.text()).toContain('environment')
    expect(wrapper.get('a[href="/audio/5"]').attributes('href')).toBe('/audio/5')
    expect(document.documentElement.lang).toBe('zh-CN')
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('language=zh-CN'))).toBe(true)
    expect(localizedAudio.tags[1]?.fullTag).toBe('topic:climate_change')
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
    expect(wrapper.text()).toContain('Author')
    expect(wrapper.text()).toContain('Second line')
    expect(wrapper.text()).toContain('Woman')
    expect(wrapper.text()).toContain('test')
    expect(wrapper.text()).toContain('气候 变化')
    expect(wrapper.findAll('dt').map((item) => item.text())).toEqual(
      expect.arrayContaining(['Author', 'Speakers', 'Topic']),
    )
    const tagSearchLinks = wrapper
      .findAll('a')
      .filter((link) => link.attributes('href')?.includes('?q='))
    expect(tagSearchLinks).toHaveLength(4)
    expect(
      tagSearchLinks.map((link) =>
        decodeURIComponent(link.attributes('href') ?? ''),
      ),
    ).toContain('/audio?q=topic:climate_change')
    expect(
      tagSearchLinks.map((link) =>
        decodeURIComponent(link.attributes('href') ?? ''),
      ),
    ).toContain('/audio?q=voice:test')
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
    expect(wrapper.find('#audio-visibility').exists()).toBe(true)
    expect(wrapper.findAll('dt').map((item) => item.text())).not.toContain('Visibility')
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

  it('edits topic and category tags without exposing voice tags', async () => {
    const voiceTag = {
      id: 3,
      type: 'voice' as const,
      englishValue: 'host',
      displayValue: 'host',
      fullTag: 'voice:host',
      translations: [],
    }
    const editableAudio = { ...audio, tags: [...audio.tags, voiceTag] }
    const categoryTag = {
      id: 4,
      type: 'category' as const,
      englishValue: 'practice',
      displayValue: 'practice',
      fullTag: 'category:practice',
      translations: [],
    }
    let updateBody: { tagIds?: number[] } | undefined
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.startsWith('/api/audios/5?')) return Promise.resolve(jsonResponse(editableAudio))
      if (path.startsWith('/api/audio-tags?')) {
        return Promise.resolve(jsonResponse([...audio.tags, voiceTag, categoryTag]))
      }
      if (path === '/api/audios/5' && init?.method === 'PATCH') {
        updateBody = JSON.parse(String(init.body))
        return Promise.resolve(
          jsonResponse({ ...audio, tags: [audio.tags[0], voiceTag, categoryTag] }),
        )
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const pinia = setupAuth(true)
    const router = testRouter()
    await router.push('/audio/5')
    const wrapper = mount(AudioDetailView, {
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Edit')?.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('input[placeholder="Search tags"]')).toHaveLength(2)

    await wrapper.get('button[title="Remove tag"]').trigger('click')
    const searchInputs = wrapper.findAll('input[placeholder="Search tags"]')
    await searchInputs[1]?.setValue('practice')
    await wrapper.get('[role="option"]').trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(updateBody?.tagIds).toEqual([4])
    expect(wrapper.text()).toContain('test')
    expect(wrapper.text()).toContain('practice')
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
