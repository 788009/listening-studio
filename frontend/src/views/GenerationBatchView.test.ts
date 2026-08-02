import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useListeningDraftsStore } from '@/stores/listeningDrafts'
import GenerationBatchView from './GenerationBatchView.vue'


const voices = {
  items: [
    {
      id: 2,
      author: { userId: 'TeacherOne', username: 'Teacher' },
      title: 'Male voice',
      status: 'ready',
      visibility: 'private',
      sampleSource: 'original',
      tags: [],
    },
    {
      id: 3,
      author: { userId: 'TeacherOne', username: 'Teacher' },
      title: 'Female voice',
      status: 'ready',
      visibility: 'private',
      sampleSource: 'original',
      tags: [],
    },
  ],
  page: 1,
  pageSize: 100,
  total: 2,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function completedBatch() {
  return {
    id: 7,
    jobId: 11,
    questionTypeCounts: { short_dialogue: 1, monologue: 1 },
    status: 'completed',
    progress: 100,
    tags: [
      { id: 4, type: 'topic', englishValue: 'travel' },
      { id: 5, type: 'category', englishValue: 'short' },
      { id: 6, type: 'category', englishValue: 'monologue' },
    ],
    speakerVoices: [
      { speaker: 'Man', voiceId: 2 },
      { speaker: 'Woman', voiceId: 3 },
    ],
    items: [
      {
        id: 21,
        position: 0,
        status: 'completed',
        attemptCount: 1,
        draft: {
          questionType: 'short_dialogue',
          title: 'Travel plans',
          utterances: [
            { speakerDisplayName: 'Man', voiceId: 2, text: 'Ready?' },
            { speakerDisplayName: 'Woman', voiceId: 3, text: 'Yes.' },
          ],
          questions: [
            { prompt: 'Are they ready?', correctAnswers: ['Yes'], incorrectAnswers: ['No'] },
          ],
        },
      },
      {
        id: 22,
        position: 1,
        status: 'completed',
        attemptCount: 1,
        draft: {
          questionType: 'monologue',
          title: 'Travel report',
          utterances: [{ speakerDisplayName: 'Woman', voiceId: 3, text: 'A report.' }],
          questions: [
            { prompt: 'What is it?', correctAnswers: ['A report'], incorrectAnswers: ['A call'] },
          ],
        },
      },
    ],
    createdAt: '',
    updatedAt: '',
  }
}

async function mountView(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/generate', name: 'generate', component: GenerationBatchView },
      { path: '/generate/:id', name: 'generation-batch', component: GenerationBatchView },
      { path: '/create', name: 'create', component: { template: '<div>create</div>' } },
    ],
  })
  const pinia = createPinia()
  await router.push(path)
  await router.isReady()
  return {
    pinia,
    router,
    wrapper: mount(GenerationBatchView, {
      global: { plugins: [pinia, router] },
    }),
  }
}

describe('corpus generation view', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('submits source, one selected type, count, speakers, and voices', async () => {
    let submitted: FormData | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        if (path.startsWith('/api/voices')) return Promise.resolve(jsonResponse(voices))
        if (path === '/api/generation-batches' && init?.method === 'POST') {
          submitted = init.body as FormData
          return Promise.resolve(jsonResponse({ batchId: 7, jobId: 11 }, 202))
        }
        if (path === '/api/generation-batches/7') {
          return Promise.resolve(jsonResponse({ ...completedBatch(), status: 'processing', progress: 25 }))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { router, wrapper } = await mountView('/generate')
    await flushPromises()

    await wrapper.get('#corpus-text').setValue('A travel corpus')
    await wrapper.get('#speaker-name-1').setValue('Man')
    await wrapper.get('#speaker-name-2').setValue('Woman')
    await wrapper.get('#speaker-voice-2').setValue('3')
    await wrapper.get('#question-type-long_dialogue').setValue()
    await wrapper.get('#question-count').setValue('2')
    expect((wrapper.get('#question-type-short_dialogue').element as HTMLInputElement).checked).toBe(false)
    expect((wrapper.get('#question-type-long_dialogue').element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/generate/7')
    expect(submitted?.get('corpus')).toBe('A travel corpus')
    expect(submitted?.get('questionType')).toBe('long_dialogue')
    expect(submitted?.get('count')).toBe('2')
    expect(submitted?.has('questionTypeCounts')).toBe(false)
    expect(JSON.parse(String(submitted?.get('speakerVoiceMap')))).toEqual({ Man: 2, Woman: 3 })
    wrapper.unmount()
  })

  it('moves completed drafts and suggested topics into the creation workflow', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input)
        if (path.startsWith('/api/voices')) return Promise.resolve(jsonResponse(voices))
        if (path === '/api/generation-batches/7') return Promise.resolve(jsonResponse(completedBatch()))
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { pinia, router, wrapper } = await mountView('/generate/7')
    await flushPromises()

    const store = useListeningDraftsStore(pinia)
    expect(router.currentRoute.value.fullPath).toBe('/create?batch=7')
    expect(store.drafts).toHaveLength(2)
    expect(store.drafts[0]?.title).toBe('Travel plans')
    expect(store.drafts[0]?.tagIds).toEqual([4, 5])
    expect(store.drafts[1]?.questionType).toBe('monologue')
    expect(store.drafts[1]?.tagIds).toEqual([4, 6])
    wrapper.unmount()
  })

  it('validates type count, dialogue speakers, and file errors', async () => {
    let submissions = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        if (path.startsWith('/api/voices')) return Promise.resolve(jsonResponse(voices))
        if (path === '/api/generation-batches' && init?.method === 'POST') {
          submissions += 1
          return Promise.resolve(
            jsonResponse(
              { error: { code: 'validation_error', message: 'Corpus file does not match the declared encoding', details: null, request_id: 'request-1' } },
              422,
            ),
          )
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const { wrapper } = await mountView('/generate')
    await flushPromises()
    await wrapper.get('#corpus-text').setValue('Corpus')
    await wrapper.get('#question-count').setValue('21')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('between 1 and 20')

    await wrapper.get('#question-count').setValue('1')
    await wrapper.get('#speaker-name-1').setValue('')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('unique name and voice')
    expect(submissions).toBe(0)

    await wrapper.get('#speaker-name-1').setValue('Man')
    await wrapper.findAll('button').find((item) => item.text() === 'TXT file')?.trigger('click')
    const fileInput = wrapper.get('#corpus-file')
    Object.defineProperty(fileInput.element, 'files', {
      value: [new File(['corpus'], 'corpus.txt', { type: 'text/plain' })],
    })
    await fileInput.trigger('change')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('declared encoding')
    expect(submissions).toBe(1)
    wrapper.unmount()
  })
})
