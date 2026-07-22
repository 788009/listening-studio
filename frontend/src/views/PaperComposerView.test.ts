import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

import type { Audio, AudioTag } from '@/api/audios'
import { useAuthStore } from '@/stores/auth'
import PaperComposerView from './PaperComposerView.vue'

const topicTag: AudioTag = {
  id: 8,
  type: 'topic',
  englishValue: 'news',
  displayValue: 'News',
  fullTag: 'topic:news',
  translations: [],
}

const fullPaperTag: AudioTag = {
  id: 7,
  type: 'category',
  englishValue: 'full_paper',
  displayValue: 'Full paper',
  fullTag: 'category:full_paper',
  translations: [],
}

const audio: Audio = {
  id: 5,
  author: { userId: 'TeacherOne', username: 'Teacher One' },
  title: 'Listening section',
  text: 'Listening text.',
  sourceType: 'corpus',
  status: 'ready',
  visibility: 'public',
  durationSeconds: 30,
  sampleRate: 8000,
  tags: [topicTag],
  utterances: [],
  questions: [
    {
      id: 1,
      position: 0,
      prompt: 'Question?',
      correctAnswers: ['A'],
      incorrectAnswers: ['B'],
    },
  ],
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function mountView(role: 'user' | 'admin' = 'user') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/papers/new', name: 'paper-create', component: PaperComposerView },
      { path: '/audio/:id', name: 'audio', component: { template: '<div />' } },
    ],
  })
  await router.push('/papers/new')
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setCurrentUser({
    userId: 'TeacherOne',
    username: 'Teacher One',
    locale: 'en',
    profileComplete: true,
    role,
  })
  return {
    router,
    wrapper: mount(RouterView, { global: { plugins: [pinia, router] } }),
  }
}

describe('paper composer view', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps the current playback until a new preview is ready', async () => {
    vi.useFakeTimers()
    const previewBodies: Record<string, unknown>[] = []
    let nextPreviewId = 30
    let secondJobReads = 0
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    const pause = vi
      .spyOn(HTMLMediaElement.prototype, 'pause')
      .mockImplementation(() => undefined)
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        if (path === '/api/assembly-templates') return Promise.resolve(response([]))
        if (path.startsWith('/api/audio-tags')) {
          return Promise.resolve(response([fullPaperTag, topicTag]))
        }
        if (path.startsWith('/api/audios?')) {
          return Promise.resolve(response({ items: [audio], page: 1, pageSize: 10, total: 1 }))
        }
        if (path === '/api/assembly-previews' && init?.method === 'POST') {
          previewBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>)
          nextPreviewId += 1
          return Promise.resolve(response({ jobId: nextPreviewId }, 202))
        }
        if (path.match(/^\/api\/jobs\/3[12]$/)) {
          const id = Number(path.slice(path.lastIndexOf('/') + 1))
          if (id === 32) secondJobReads += 1
          const succeeded = id === 31 || secondJobReads > 1
          return Promise.resolve(
            response({
              id,
              type: 'assembly_preview',
              status: succeeded ? 'succeeded' : 'running',
              progress: succeeded ? 100 : 50,
              inputSummary: {},
              result: succeeded ? { type: 'assembly_preview', id } : undefined,
              cancelRequested: false,
              retryable: false,
              attemptCount: 1,
              createdAt: '',
              updatedAt: '',
            }),
          )
        }
        if (path.match(/^\/api\/assembly-previews\/3[12]$/) && init?.method === 'DELETE') {
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { wrapper } = await mountView()
    await flushPromises()
    const searchSection = wrapper.get('[aria-labelledby="audio-source-title"]')
    const segmentsSection = wrapper.get('[aria-labelledby="segments-title"]')
    expect(searchSection.classes()).toEqual(expect.arrayContaining(['order-2', 'xl:order-1']))
    expect(segmentsSection.classes()).toEqual(expect.arrayContaining(['order-1', 'xl:order-2']))
    const searchResults = wrapper.get('[aria-labelledby="audio-source-title"] ul')
    expect(searchResults.classes()).toContain('max-h-[63vh]')
    expect(searchResults.classes()).toContain('overflow-y-auto')
    await wrapper.findAll('button').find((button) => button.text() === 'Add')?.trigger('click')
    const segmentList = wrapper.get('[aria-labelledby="segments-title"] ol')
    expect(segmentList.classes()).toContain('max-h-[80vh]')
    expect(segmentList.classes()).toContain('overflow-y-auto')

    await wrapper.findAll('button').find((button) => button.text() === 'Play')?.trigger('click')
    await flushPromises()
    expect(previewBodies[0]).toMatchObject({ startIndex: 0, endIndex: 0 })
    expect(wrapper.find('audio[src="/media/assembly-preview/31"]').exists()).toBe(true)
    expect(pause).not.toHaveBeenCalled()

    await wrapper.findAll('input[type="number"]')[0]?.setValue('2')
    await flushPromises()
    expect(wrapper.find('audio[src="/media/assembly-preview/31"]').exists()).toBe(true)
    expect(pause).not.toHaveBeenCalled()

    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Play from here')
      ?.trigger('click')
    await flushPromises()
    expect(previewBodies[1]).toMatchObject({ startIndex: 0 })
    expect(previewBodies[1]).not.toHaveProperty('endIndex')
    expect(wrapper.find('audio[src="/media/assembly-preview/31"]').exists()).toBe(true)
    expect(pause).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(wrapper.find('audio[src="/media/assembly-preview/32"]').exists()).toBe(true)
    expect(pause).toHaveBeenCalledTimes(1)
    wrapper.unmount()
    await flushPromises()
  })

  it('adds configurable audio and silence segments and submits an assembly', async () => {
    vi.useFakeTimers()
    let submitted: Record<string, unknown> | undefined
    let jobReads = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        if (path === '/api/assembly-templates') return Promise.resolve(response([]))
        if (path.startsWith('/api/audio-tags')) {
          return Promise.resolve(response([fullPaperTag, topicTag]))
        }
        if (path.startsWith('/api/audios?')) {
          return Promise.resolve(response({ items: [audio], page: 1, pageSize: 10, total: 1 }))
        }
        if (path === '/api/assemblies' && init?.method === 'POST') {
          submitted = JSON.parse(String(init.body)) as Record<string, unknown>
          return Promise.resolve(response({ audioId: 12, jobId: 20 }, 202))
        }
        if (path === '/api/jobs/20') {
          jobReads += 1
          return Promise.resolve(
            response({
              id: 20,
              type: 'audio_assembly',
              status: jobReads > 1 ? 'succeeded' : 'running',
              progress: jobReads > 1 ? 100 : 40,
              inputSummary: {},
              result: jobReads > 1 ? { type: 'audio', id: 12 } : undefined,
              cancelRequested: false,
              retryable: true,
              attemptCount: 1,
              createdAt: '',
              updatedAt: '',
            }),
          )
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { router, wrapper } = await mountView()
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Add')?.trigger('click')
    const segmentList = wrapper.get('[aria-labelledby="segments-title"] ol')
    Object.defineProperty(segmentList.element, 'scrollHeight', {
      configurable: true,
      value: 720,
    })
    segmentList.element.scrollTop = 0
    await wrapper.findAll('button').find((button) => button.text() === 'Add silence')?.trigger('click')
    await flushPromises()
    expect(segmentList.element.scrollTop).toBe(720)
    await wrapper.findAll('button').find((button) => button.text() === 'Select')?.trigger('click')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Add silence')).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Cancel')).toBe(true)
    let segmentCheckboxes = wrapper.findAll('input[aria-label^="Select segment"]')
    expect(segmentCheckboxes).toHaveLength(2)
    await segmentCheckboxes[0]?.setValue(true)
    segmentList.element.scrollTop = 0
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Copy and add to end')
      ?.trigger('click')
    await flushPromises()
    expect(segmentList.element.scrollTop).toBe(720)
    segmentCheckboxes = wrapper.findAll('input[aria-label^="Select segment"]')
    expect(segmentCheckboxes).toHaveLength(3)
    await segmentCheckboxes[2]?.setValue(true)
    await wrapper.findAll('button').find((button) => button.text() === 'Delete')?.trigger('click')
    expect(wrapper.findAll('input[aria-label^="Select segment"]')).toHaveLength(2)
    await wrapper.findAll('button').find((button) => button.text() === 'Cancel')?.trigger('click')
    expect(wrapper.find('input[aria-label^="Select segment"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Add silence')).toBe(true)
    const preview = wrapper.get('[aria-labelledby="assembly-preview-title"]')
    expect(preview.text()).toContain('Listening text.')
    expect(preview.text()).toContain('Question?')
    expect(preview.text().match(/Question\?/g)).toHaveLength(1)
    expect(wrapper.text()).toContain('Tags')
    expect(wrapper.text()).not.toContain('Final tags')
    expect(wrapper.find('button[aria-label="Remove News"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="Remove Full paper"]').exists()).toBe(false)
    await wrapper.get('button[aria-label="Remove News"]').trigger('click')
    await wrapper.get('input[maxlength="200"]').setValue('Final exam')
    const numberInputs = wrapper.findAll('input[type="number"]')
    expect((numberInputs[1]?.element as HTMLInputElement).value).toBe('1')
    expect((numberInputs[2]?.element as HTMLInputElement).value).toBe('5')
    await numberInputs[0]?.setValue('2')
    await numberInputs[1]?.setValue('1.5')
    await wrapper.findAll('button').find((button) => button.text() === 'Assemble and publish')?.trigger('click')
    await flushPromises()

    expect(submitted).toMatchObject({
      title: 'Final exam',
      tagIds: [7],
      visibility: 'public',
      segments: [
        {
          type: 'audio',
          audioId: 5,
          repeatCount: 2,
          repeatIntervalMilliseconds: 1500,
          includeText: true,
          includeTopic: true,
        },
        { type: 'silence', silenceMilliseconds: 5000 },
      ],
    })
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/audio/12')
    wrapper.unmount()
  })

  it('applies a suggested query when filling a template placeholder', async () => {
    const requests: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input)
        requests.push(path)
        if (path === '/api/assembly-templates') {
          return Promise.resolve(
            response([
              {
                id: 3,
                title: 'Exam template',
                ownerUserId: 'Admin',
                createdAt: '',
                updatedAt: '',
                segments: [
                  {
                    id: 1,
                    position: 0,
                    type: 'smart',
                    repeatCount: 1,
                    repeatIntervalMilliseconds: 0,
                    silenceMilliseconds: 0,
                    includeText: false,
                    includeTopic: false,
                  },
                  {
                    id: 2,
                    position: 1,
                    type: 'placeholder',
                    suggestedQuery: 'topic:news',
                    repeatCount: 1,
                    repeatIntervalMilliseconds: 0,
                    silenceMilliseconds: 0,
                    includeText: true,
                    includeTopic: true,
                  },
                ],
              },
            ]),
          )
        }
        if (path.startsWith('/api/audio-tags')) return Promise.resolve(response([]))
        if (path.startsWith('/api/audios?')) {
          return Promise.resolve(response({ items: [audio], page: 1, pageSize: 10, total: 1 }))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { wrapper } = await mountView('admin')
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === 'Add smart segment')
      ?.trigger('click')
    expect(wrapper.findAll('[aria-labelledby="segments-title"] ol > li')).toHaveLength(1)
    const smartSegment = wrapper.get('[aria-labelledby="segments-title"] ol > li')
    const includeText = smartSegment
      .findAll('label')
      .find((label) => label.text() === 'Include text')
      ?.get('input')
    const includeTopic = smartSegment
      .findAll('label')
      .find((label) => label.text() === 'Include topic')
      ?.get('input')
    expect((includeText?.element as HTMLInputElement).checked).toBe(false)
    expect((includeTopic?.element as HTMLInputElement).checked).toBe(false)
    await includeText?.setValue(true)
    await includeTopic?.setValue(true)
    expect((includeText?.element as HTMLInputElement).checked).toBe(true)
    expect((includeTopic?.element as HTMLInputElement).checked).toBe(true)
    await wrapper.find('select').setValue('3')
    await flushPromises()
    const smartMode = wrapper
      .findAll('select')
      .find((item) => item.find('option[value="question_count_silence"]').exists())
    await smartMode?.setValue('question_count_silence')
    expect(wrapper.text()).toContain('Question-count smart silence')
    expect(
      (wrapper.find('input[type="number"][max="60"]').element as HTMLInputElement).value,
    ).toBe('5')
    const association = wrapper
      .findAll('select')
      .find((item) => item.find('option[value="previous"]').exists())
    expect(association?.findAll('option').map((option) => option.text())).toEqual([
      'Select a placeholder',
      'Previous placeholder',
      'Next placeholder',
    ])
    await association?.setValue('previous')
    expect((association?.element as HTMLSelectElement).value).toBe('previous')
    await wrapper.findAll('button').find((button) => button.text() === 'Choose audio')?.trigger('click')
    await flushPromises()

    expect(requests.some((path) => path.includes('q=topic%3Anews'))).toBe(true)
    expect(wrapper.text()).toContain('Question-count smart silence')
    wrapper.unmount()
  })
})
