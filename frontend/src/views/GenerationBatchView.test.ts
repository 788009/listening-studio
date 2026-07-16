import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import GenerationBatchView from './GenerationBatchView.vue'


const voices = {
  items: [
    {
      id: 2,
      author: { userId: 'TeacherOne', username: 'Teacher' },
      title: 'Host voice',
      status: 'ready',
      visibility: 'private',
      sampleSource: 'original',
      tags: [],
    },
    {
      id: 3,
      author: { userId: 'TeacherOne', username: 'Teacher' },
      title: 'Guest voice',
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

const topic = {
  id: 4,
  type: 'topic',
  displayValue: 'climate_change',
  englishValue: 'climate_change',
  fullTag: 'topic:climate_change',
  translations: [],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function batchResponse(completed = false) {
  return {
    id: 7,
    jobId: 11,
    questionTypes: ['multiple_choice'],
    requestedCount: 2,
    status: completed ? 'completed' : 'failed',
    progress: 100,
    tags: [{ id: 4, type: 'topic', englishValue: 'climate_change' }],
    speakerVoices: [
      { speaker: 'Host', voiceId: 2 },
      { speaker: 'Guest', voiceId: 3 },
    ],
    items: [
      {
        id: 21,
        position: 0,
        status: 'completed',
        audioId: 31,
        title: 'Climate interview',
        questionTypes: ['multiple_choice'],
        attemptCount: 1,
      },
      {
        id: 22,
        position: 1,
        status: completed ? 'completed' : 'failed',
        audioId: 32,
        title: 'Climate report',
        errorSummary: completed ? undefined : 'Audio generation failed',
        questionTypes: ['multiple_choice'],
        attemptCount: completed ? 2 : 1,
      },
    ],
    errorSummary: completed ? undefined : 'One or more generated audios failed',
    createdAt: '',
    updatedAt: '',
  }
}

function optionsResponse(path: string): Response | null {
  if (path.startsWith('/api/voices')) return jsonResponse(voices)
  if (path.includes('type=topic')) return jsonResponse([topic])
  if (path.includes('type=category')) return jsonResponse([])
  return null
}

async function mountView(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/generate', name: 'generate', component: GenerationBatchView },
      {
        path: '/generate/:id',
        name: 'generation-batch',
        component: GenerationBatchView,
      },
      { path: '/audio/:id', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  return {
    router,
    wrapper: mount(GenerationBatchView, {
      global: { plugins: [createPinia(), router] },
    }),
  }
}

describe('corpus generation view', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('submits corpus controls and persists the batch ID in the route', async () => {
    let submitted: FormData | undefined
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/generation-batches' && init?.method === 'POST') {
        submitted = init.body as FormData
        return Promise.resolve(jsonResponse({ batchId: 7, jobId: 11 }, 202))
      }
      if (path === '/api/generation-batches/7') {
        return Promise.resolve(
          jsonResponse({ ...batchResponse(), status: 'processing', progress: 25 }),
        )
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { router, wrapper } = await mountView('/generate')
    await flushPromises()

    await wrapper.get('#corpus-text').setValue('A climate corpus')
    await wrapper.get('#speaker-voice-2').setValue('3')
    await wrapper.get('input[type="number"]').setValue('2')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/generate/7')
    expect(submitted?.get('corpus')).toBe('A climate corpus')
    expect(submitted?.getAll('questionTypes')).toEqual(['multiple_choice'])
    expect(JSON.parse(String(submitted?.get('speakerVoiceMap')))).toEqual({
      Host: 2,
      Guest: 3,
    })
    expect(wrapper.text()).toContain('Batch 7')
    wrapper.unmount()
  })

  it('restores a mixed batch, retries one item, and updates completed audios', async () => {
    let reads = 0
    let updateBody: unknown
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/generation-batches/7') {
        reads += 1
        return Promise.resolve(jsonResponse(batchResponse(reads > 1)))
      }
      if (path === '/api/generation-batches/7/items/22/retry') {
        return Promise.resolve(jsonResponse({ batchId: 7, itemId: 22, jobId: 12 }, 202))
      }
      if (path === '/api/generation-batches/7/completed-audios') {
        updateBody = JSON.parse(String(init?.body))
        return Promise.resolve(jsonResponse({ updatedCount: 2 }))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { wrapper } = await mountView('/generate/7')
    await flushPromises()

    expect(wrapper.text()).toContain('Climate interview')
    expect(wrapper.text()).toContain('Audio generation failed')
    await wrapper.findAll('button').find((button) => button.text() === 'Retry')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Climate report')
    expect(wrapper.text()).not.toContain('Audio generation failed')

    const visibility = wrapper.findAll('label').find((label) =>
      label.text().includes('Public visibility'),
    )
    await visibility?.get('input').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(updateBody).toEqual({ tagIds: [4], visibility: 'public' })
    expect(wrapper.text()).toContain('2 completed audios updated')
    wrapper.unmount()
  })

  it('validates count and mappings and shows server upload errors', async () => {
    let submissions = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/generation-batches' && init?.method === 'POST') {
        submissions += 1
        return Promise.resolve(
          jsonResponse(
            {
              error: {
                code: 'validation_error',
                message: 'Corpus file does not match the declared encoding',
                details: null,
                request_id: 'request-1',
              },
            },
            422,
          ),
        )
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { wrapper } = await mountView('/generate')
    await flushPromises()
    await wrapper.get('#corpus-text').setValue('Corpus')
    await wrapper.get('#generation-count').setValue('21')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('between 1 and 20')
    expect(submissions).toBe(0)

    await wrapper.get('#generation-count').setValue('1')
    await wrapper.get('#speaker-1').setValue('')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('speaker and voice mapping')
    expect(submissions).toBe(0)

    await wrapper.get('#speaker-1').setValue('Host')
    await wrapper.findAll('button').find((button) => button.text() === 'TXT file')?.trigger('click')
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
