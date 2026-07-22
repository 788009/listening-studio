import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

import type { Audio } from '@/api/audios'
import { useAuthStore } from '@/stores/auth'
import PaperComposerView from './PaperComposerView.vue'

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
  tags: [],
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
    vi.unstubAllGlobals()
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
          return Promise.resolve(
            response([
              {
                id: 7,
                type: 'category',
                englishValue: 'full_paper',
                displayValue: 'Full paper',
                fullTag: 'category:full_paper',
                translations: [],
              },
            ]),
          )
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
    await wrapper.findAll('button').find((button) => button.text() === 'Add silence')?.trigger('click')
    await wrapper.get('input[maxlength="200"]').setValue('Final exam')
    const numberInputs = wrapper.findAll('input[type="number"]')
    await numberInputs[0]?.setValue('2')
    await numberInputs[1]?.setValue('1500')
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
        { type: 'silence', silenceMilliseconds: 3000 },
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
    const { wrapper } = await mountView()
    await flushPromises()
    await wrapper.find('select').setValue('3')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Choose audio')?.trigger('click')
    await flushPromises()

    expect(requests.some((path) => path.includes('q=topic%3Anews'))).toBe(true)
    expect(wrapper.text()).toContain('Smart question-number audio')
    wrapper.unmount()
  })
})
