import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

import type { Audio } from '@/api/audios'
import { useAuthStore } from '@/stores/auth'
import AudioDetailView from './AudioDetailView.vue'
import PaperComposerView from './PaperComposerView.vue'

const firstAudio: Audio = {
  id: 1,
  author: { userId: 'TeacherOne', username: 'Teacher One' },
  title: 'First report',
  text: 'First transcript.',
  sourceType: 'corpus',
  status: 'ready',
  visibility: 'private',
  durationSeconds: 30,
  sampleRate: 8000,
  tags: [],
  utterances: [],
}

const secondAudio: Audio = {
  ...firstAudio,
  id: 2,
  title: 'Second interview',
  text: 'Second transcript.',
  durationSeconds: 45,
  visibility: 'public',
}

const resultAudio: Audio = {
  ...firstAudio,
  id: 9,
  title: 'Midterm paper',
  text: '1. Second interview\nSecond transcript.\n\n1. First report\nFirst transcript.',
  sourceType: 'assembly',
  durationSeconds: 160,
}

const presets = [
  {
    id: 1,
    name: 'Standard',
    isBuiltin: true,
    introSilenceMilliseconds: 1000,
    interItemSilenceMilliseconds: 3000,
    repeatCount: 1,
    outroSilenceMilliseconds: 1000,
  },
  {
    id: 2,
    name: 'Review',
    isBuiltin: true,
    introSilenceMilliseconds: 1000,
    interItemSilenceMilliseconds: 5000,
    repeatCount: 2,
    outroSilenceMilliseconds: 1000,
  },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(status: number, message: string): Response {
  return jsonResponse(
    {
      error: {
        code: 'not_found',
        message,
        details: null,
        request_id: 'request-test',
      },
    },
    status,
  )
}

function setupAuth() {
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

async function mountWorkflow() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/papers/new',
        name: 'paper-create',
        component: PaperComposerView,
      },
      {
        path: '/audio/:id',
        name: 'audio',
        component: AudioDetailView,
      },
      { path: '/', name: 'library', component: { template: '<div />' } },
      { path: '/user/:userId', component: { template: '<div />' } },
    ],
  })
  await router.push('/papers/new')
  await router.isReady()
  const pinia = setupAuth()
  return {
    router,
    wrapper: mount(RouterView, { global: { plugins: [pinia, router] } }),
  }
}

function optionResponse(path: string): Response | null {
  if (path === '/api/paper-presets') return jsonResponse(presets)
  if (path.startsWith('/api/audio-tags')) return jsonResponse([])
  return null
}

describe('paper composer view', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('selects, orders, renders, and plays the final assembly audio', async () => {
    vi.useFakeTimers()
    let paperBody: unknown
    let jobReads = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const option = optionResponse(path)
      if (option) return Promise.resolve(option)
      if (path.startsWith('/api/audios?')) {
        return Promise.resolve(
          jsonResponse({ items: [firstAudio, secondAudio], page: 1, pageSize: 10, total: 2 }),
        )
      }
      if (path === '/api/audios/1?language=en') return Promise.resolve(jsonResponse(firstAudio))
      if (path === '/api/audios/2?language=en') return Promise.resolve(jsonResponse(secondAudio))
      if (path === '/api/audios/9?language=en') return Promise.resolve(jsonResponse(resultAudio))
      if (path === '/api/papers' && init?.method === 'POST') {
        paperBody = JSON.parse(String(init.body))
        return Promise.resolve(jsonResponse({ id: 7 }, 201))
      }
      if (path === '/api/papers/7/render') {
        return Promise.resolve(jsonResponse({ paperId: 7, audioId: 9, jobId: 11 }, 202))
      }
      if (path === '/api/jobs/11') {
        jobReads += 1
        return Promise.resolve(
          jsonResponse({
            id: 11,
            type: 'paper_render',
            status: jobReads > 1 ? 'succeeded' : 'running',
            progress: jobReads > 1 ? 100 : 40,
            inputSummary: {},
            result: jobReads > 1 ? { type: 'audio', id: 9 } : undefined,
            cancelRequested: false,
            retryable: true,
            attemptCount: 1,
            createdAt: '',
            updatedAt: '',
          }),
        )
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { router, wrapper } = await mountWorkflow()
    await flushPromises()

    const addButtons = wrapper.findAll('button').filter((button) => button.text() === 'Add')
    await addButtons[0]?.trigger('click')
    await addButtons[1]?.trigger('click')
    await wrapper.get('button[aria-label="Move Second interview up"]').trigger('click')
    await wrapper.get('#paper-name').setValue('Midterm paper')
    await wrapper.get('#paper-preset').setValue('2')

    expect(wrapper.text()).toContain('Estimated length')
    expect(wrapper.text()).toContain('2:37')
    await wrapper.findAll('button').find((button) => button.text() === 'Render paper')?.trigger('click')
    await flushPromises()

    expect(paperBody).toEqual({
      title: 'Midterm paper',
      presetId: 2,
      audioIds: [2, 1],
    })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('40')

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/audio/9')
    expect(wrapper.text()).toContain('Midterm paper')
    expect(wrapper.get('audio').attributes('src')).toBe('/media/audio/9')
    wrapper.unmount()
  })

  it('uses server pagination instead of loading the complete audio library', async () => {
    const candidateRequests: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input)
        const option = optionResponse(path)
        if (option) return Promise.resolve(option)
        if (path.startsWith('/api/audios?')) {
          candidateRequests.push(path)
          const secondPage = path.includes('page=2')
          return Promise.resolve(
            jsonResponse({
              items: secondPage ? [secondAudio] : [firstAudio],
              page: secondPage ? 2 : 1,
              pageSize: 10,
              total: 25,
            }),
          )
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { wrapper } = await mountWorkflow()
    await flushPromises()

    expect(candidateRequests[0]).toContain('page_size=10')
    await wrapper.findAll('button').find((button) => button.text().includes('Next'))?.trigger('click')
    await flushPromises()

    expect(candidateRequests[1]).toContain('page=2')
    expect(wrapper.text()).toContain('Second interview')
    wrapper.unmount()
  })

  it('keeps inaccessible and changed items visible and blocks submission', async () => {
    let paperSubmissions = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const option = optionResponse(path)
        if (option) return Promise.resolve(option)
        if (path.startsWith('/api/audios?')) {
          return Promise.resolve(
            jsonResponse({ items: [firstAudio, secondAudio], page: 1, pageSize: 10, total: 2 }),
          )
        }
        if (path === '/api/audios/1?language=en') {
          return Promise.resolve(errorResponse(404, 'Audio not found'))
        }
        if (path === '/api/audios/2?language=en') {
          return Promise.resolve(
            jsonResponse({ ...secondAudio, status: 'processing' }),
          )
        }
        if (path === '/api/papers' && init?.method === 'POST') {
          paperSubmissions += 1
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { wrapper } = await mountWorkflow()
    await flushPromises()

    const addButtons = wrapper.findAll('button').filter((button) => button.text() === 'Add')
    await addButtons[0]?.trigger('click')
    await addButtons[1]?.trigger('click')
    await wrapper.get('#paper-name').setValue('Invalid paper')
    await wrapper.findAll('button').find((button) => button.text() === 'Render paper')?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('No longer accessible or deleted')
    expect(wrapper.text()).toContain('Status changed to Processing')
    expect(wrapper.text()).toContain('Remove or replace unavailable audio')
    expect(wrapper.text()).toContain('First report')
    expect(wrapper.text()).toContain('Second interview')
    expect(paperSubmissions).toBe(0)
    wrapper.unmount()
  })
})
