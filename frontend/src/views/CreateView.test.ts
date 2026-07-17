import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import CreateView from './CreateView.vue'

const longVoiceTitle = `Long voice ${'title '.repeat(30)}`
const voices = {
  items: [
    {
      id: 2,
      author: { userId: 'TeacherOne', username: 'Teacher' },
      title: longVoiceTitle,
      status: 'ready',
      visibility: 'private',
      sampleSource: 'original',
      tags: [],
    },
    {
      id: 3,
      author: { userId: 'TeacherTwo', username: 'Other' },
      title: 'Second voice',
      status: 'ready',
      visibility: 'public',
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

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/create', component: CreateView },
      { path: '/audio/:id', component: { template: '<div />' } },
      { path: '/voices/create', component: { template: '<div />' } },
    ],
  })
  await router.push('/create?voice=2')
  await router.isReady()
  return mount(CreateView, {
    global: { plugins: [createPinia(), router] },
  })
}

function optionsResponse(path: string): Response | null {
  if (path.startsWith('/api/voices')) return jsonResponse(voices)
  if (path.includes('type=topic')) {
    return jsonResponse([
      {
        id: 4,
        type: 'topic',
        displayValue: 'climate_change',
        englishValue: 'climate_change',
        fullTag: 'topic:climate_change',
        translations: [],
      },
    ])
  }
  if (path.includes('type=category')) return jsonResponse([])
  return null
}

describe('direct creation view', () => {
  afterEach(() => {
    vi.useRealTimers()
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('creates, polls, and links to a completed single-speaker audio', async () => {
    vi.useFakeTimers()
    let jobReads = 0
    let submittedBody: unknown
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/audio-tags' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { type: 'topic' | 'category'; value: string }
        return Promise.resolve(
          jsonResponse({
            id: body.type === 'topic' ? 5 : 6,
            type: body.type,
            displayValue: body.value,
            englishValue: body.value,
            fullTag: `${body.type}:${body.value}`,
            translations: [],
          }, 201),
        )
      }
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/audios') {
        submittedBody = JSON.parse(String(init?.body))
        return Promise.resolve(jsonResponse({ audioId: 8, jobId: 13 }, 202))
      }
      if (path === '/api/jobs/13') {
        jobReads += 1
        return Promise.resolve(
          jsonResponse({
            id: 13,
            type: 'audio_synthesis',
            status: jobReads === 1 ? 'queued' : 'succeeded',
            progress: jobReads === 1 ? 0 : 100,
            inputSummary: {},
            result: jobReads === 1 ? undefined : { type: 'audio', id: 8 },
            cancelRequested: false,
            retryable: true,
            attemptCount: jobReads === 1 ? 0 : 1,
            createdAt: '',
            updatedAt: '',
          }),
        )
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    await flushPromises()
    const longText = 'Listening text '.repeat(200)
    await wrapper.get('#audio-title').setValue('Single practice')
    await wrapper.get('#single-text').setValue(longText)
    await wrapper.get('#new-topic-tag').setValue('test_topic')
    await wrapper.get('#new-category-tag').setValue('test_category')
    const addTagButtons = wrapper.findAll('button').filter((button) => button.text() === 'Add tag')
    await addTagButtons[0]?.trigger('click')
    await flushPromises()
    await addTagButtons[1]?.trigger('click')
    await flushPromises()
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Waiting for processing')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.text()).toContain('Audio is ready')
    expect(wrapper.get('a[href="/audio/8"]').attributes('href')).toBe('/audio/8')
    expect((submittedBody as { text: string }).text).toBe(longText.trim())
    expect((submittedBody as { tagIds: number[] }).tagIds).toEqual([5, 6])
    wrapper.unmount()
  })

  it('reorders dialogue turns and retains the form after a failed job retry', async () => {
    const dialogueBodies: unknown[] = []
    let submissions = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/audios/dialogues') {
        dialogueBodies.push(JSON.parse(String(init?.body)))
        submissions += 1
        return Promise.resolve(
          jsonResponse(
            { audioId: submissions === 1 ? 10 : 11, jobId: submissions === 1 ? 20 : 21 },
            202,
          ),
        )
      }
      if (path === '/api/jobs/20') {
        return Promise.resolve(
          jsonResponse({
            id: 20,
            type: 'audio_synthesis',
            status: 'failed',
            progress: 40,
            inputSummary: {},
            errorSummary: 'Verify the selected voice and try again.',
            cancelRequested: false,
            retryable: true,
            attemptCount: 1,
            createdAt: '',
            updatedAt: '',
          }),
        )
      }
      if (path === '/api/jobs/21') {
        return Promise.resolve(
          jsonResponse({
            id: 21,
            type: 'audio_synthesis',
            status: 'succeeded',
            progress: 100,
            inputSummary: {},
            result: { type: 'audio', id: 11 },
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
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.get('#audio-title').setValue('Dialogue practice')
    await wrapper.findAll('button').find((button) => button.text() === 'Dialogue')?.trigger('click')
    await wrapper.get('#turn-speaker-1').setValue('Alice')
    await wrapper.get('#turn-text-1').setValue('First line '.repeat(80))
    await wrapper.findAll('button').find((button) => button.text().includes('Add turn'))?.trigger('click')
    await wrapper.get('#turn-voice-2').setValue('3')
    await wrapper.get('#turn-speaker-2').setValue('Bob')
    await wrapper.get('#turn-text-2').setValue('Second line')
    await wrapper.findAll('button').find((button) => button.text().includes('Add turn'))?.trigger('click')
    await wrapper.get('button[aria-label="Delete turn 3"]').trigger('click')
    expect(wrapper.find('#turn-text-3').exists()).toBe(false)
    await wrapper.get('button[aria-label="Move turn 2 up"]').trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('Verify the selected voice')
    expect(wrapper.get('#turn-speaker-2').element).toHaveProperty('value', 'Bob')
    expect(wrapper.classes()).toContain('min-w-0')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(dialogueBodies).toHaveLength(2)
    expect((dialogueBodies[0] as { utterances: { text: string }[] }).utterances[0]?.text).toBe('Second line')
    expect(wrapper.get('a[href="/audio/11"]').attributes('href')).toBe('/audio/11')
    wrapper.unmount()
  })
})
