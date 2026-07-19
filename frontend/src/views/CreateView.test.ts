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

  it('opens in single-speaker mode with the requested voice selected', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const response = optionsResponse(String(input))
        if (response) return Promise.resolve(response)
        throw new Error(`Unexpected request: ${String(input)}`)
      }),
    )

    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.get('button[aria-pressed="true"]').text()).toBe('Single')
    expect(wrapper.get('#speaker-voice-1').element).toHaveProperty('value', '2')
    expect(wrapper.get('#turn-speaker-1').text()).toContain('Speaker 1')
    expect(wrapper.text()).not.toContain('climate change')
    wrapper.unmount()
  })

  it('creates an audio and opens a fresh form after leaving the completed view', async () => {
    vi.useFakeTimers()
    let jobReads = 0
    let submittedBody: unknown
    let createdTagBody: unknown
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/audio-tags' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as {
          type: 'topic' | 'category'
          value: string
          translations: { language: string; value: string }[]
        }
        createdTagBody = body
        return Promise.resolve(
          jsonResponse({
            id: 6,
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
    await wrapper.get('#speaker-name-1').setValue('Woman')
    await wrapper.get('#turn-text-1').setValue(longText)

    const searchInputs = wrapper.findAll('input[placeholder="Search tags"]')
    expect(searchInputs).toHaveLength(2)
    await searchInputs[0]?.setValue('climate')
    expect(wrapper.get('[role="option"]').text()).toContain('climate change')
    await wrapper.get('[role="option"]').trigger('click')

    const createButtons = wrapper
      .findAll('button')
      .filter((button) => button.text() === 'Create tag')
    await createButtons[1]?.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('Create Category tag')
    await wrapper.get('[role="dialog"]').trigger('submit')
    expect(wrapper.get('[role="dialog"] [role="alert"]').text()).toContain(
      'Enter a valid English tag value',
    )
    await wrapper.get('#tag-english-value').setValue('Test Category')
    await wrapper.get('#tag-translation-zh-CN').setValue('测试 分类')
    expect(wrapper.get('[role="dialog"]').text()).toContain('Test_Category')
    await wrapper.get('[role="dialog"]').trigger('submit')
    await flushPromises()

    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Waiting for processing')
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(wrapper.text()).toContain('Audio is ready')
    expect(wrapper.get('a[href="/audio/8"]').attributes('href')).toBe('/audio/8')
    expect((submittedBody as { text: string }).text).toBe(longText.trim())
    expect((submittedBody as { voiceId: number }).voiceId).toBe(2)
    expect((submittedBody as { speakerDisplayName: string }).speakerDisplayName).toBe('Woman')
    expect((submittedBody as { tagIds: number[] }).tagIds).toEqual([4, 6])
    expect(createdTagBody).toEqual({
      type: 'category',
      value: 'Test_Category',
      translations: [{ language: 'zh-CN', value: '测试_分类' }],
    })
    expect(localStorage.getItem('listening.audioCreation')).not.toBeNull()
    wrapper.unmount()

    expect(localStorage.getItem('listening.audioCreation')).toBeNull()
    const freshWrapper = await mountView()
    await flushPromises()
    expect(freshWrapper.find('#audio-title').exists()).toBe(true)
    expect(freshWrapper.text()).not.toContain('Audio is ready')
    freshWrapper.unmount()
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
    await wrapper.get('#speaker-name-1').setValue('Alice')
    await wrapper.get('#turn-text-1').setValue('First line '.repeat(80))
    await wrapper.findAll('button').find((button) => button.text() === 'Add speaker')?.trigger('click')
    await wrapper.get('#speaker-name-2').setValue('Bob')
    await wrapper.get('#speaker-voice-2').setValue('3')
    await wrapper.findAll('button').find((button) => button.text() === 'Add turn')?.trigger('click')
    await wrapper.get('#turn-speaker-2').setValue('2')
    await wrapper.get('#turn-text-2').setValue('Second line')
    await wrapper.findAll('button').find((button) => button.text() === 'Add turn')?.trigger('click')
    await wrapper.get('button[aria-label="Delete turn 3"]').trigger('click')
    expect(wrapper.find('#turn-text-3').exists()).toBe(false)
    await wrapper.get('button[aria-label="Move turn 2 up"]').trigger('click')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('Verify the selected voice')
    expect(wrapper.get('#speaker-name-2').element).toHaveProperty('value', 'Bob')
    expect(wrapper.classes()).toContain('min-w-0')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(dialogueBodies).toHaveLength(2)
    expect(
      (dialogueBodies[0] as {
        utterances: { voiceId: number; speakerDisplayName: string; text: string }[]
      }).utterances[0],
    ).toEqual({ voiceId: 3, speakerDisplayName: 'Bob', text: 'Second line' })
    expect(wrapper.get('a[href="/audio/11"]').attributes('href')).toBe('/audio/11')
    wrapper.unmount()
  })
})
