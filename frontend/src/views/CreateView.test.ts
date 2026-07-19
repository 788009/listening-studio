import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import CreateView from './CreateView.vue'

const voices = {
  items: [
    {
      id: 2,
      author: { userId: 'TeacherOne', username: 'Teacher' },
      title: 'First voice',
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

function emptyResponse(status = 204): Response {
  return new Response(null, { status })
}

function optionsResponse(path: string): Response | null {
  if (path.startsWith('/api/voices')) return jsonResponse(voices)
  if (path.includes('type=topic')) return jsonResponse([])
  if (path.includes('type=category')) return jsonResponse([])
  return null
}

function jobResponse(
  id: number,
  status: 'queued' | 'running' | 'succeeded' | 'failed',
): Response {
  return jsonResponse({
    id,
    type: 'audio_utterance_preview',
    status,
    progress: status === 'succeeded' ? 100 : status === 'failed' ? 60 : 20,
    inputSummary: {},
    result: status === 'succeeded' ? { type: 'audio_preview', id } : undefined,
    errorSummary: status === 'failed' ? 'Preview synthesis failed' : undefined,
    cancelRequested: false,
    retryable: true,
    attemptCount: 1,
    createdAt: '',
    updatedAt: '',
  })
}

function publishedAudio(id: number) {
  return {
    id,
    author: { userId: 'TeacherOne', username: 'Teacher' },
    title: 'Dialogue practice',
    text: 'Second line.\nChanged first line.',
    sourceType: 'multi_turn',
    status: 'ready',
    visibility: 'private',
    durationSeconds: 1,
    sampleRate: 8000,
    tags: [],
    utterances: [],
  }
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
  return mount({ template: '<router-view />' }, {
    global: { plugins: [createPinia(), router] },
  })
}

function button(wrapper: Awaited<ReturnType<typeof mountView>>, label: string) {
  const match = wrapper.findAll('button').find((item) => item.text() === label)
  if (!match) throw new Error(`Button not found: ${label}`)
  return match
}

describe('direct creation view', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('opens with one speaker and the requested voice selected', async () => {
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

    expect(wrapper.get('#speaker-voice-1').element).toHaveProperty('value', '2')
    expect(wrapper.get('#turn-speaker-1').text()).toContain('Speaker 1')
    expect(button(wrapper, 'Generate preview').exists()).toBe(true)
    expect(button(wrapper, 'Generate audio').exists()).toBe(true)
    wrapper.unmount()
  })

  it('generates, invalidates, reorders, previews, and publishes turns', async () => {
    const previewBodies: unknown[] = []
    const deletedJobs: number[] = []
    let publishBody: unknown
    let nextJobId = 10
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/audio-previews' && init?.method === 'POST') {
        previewBodies.push(JSON.parse(String(init.body)))
        const jobId = nextJobId++
        return Promise.resolve(jsonResponse({ jobId, contentDigest: 'a'.repeat(64) }, 202))
      }
      const jobMatch = path.match(/^\/api\/jobs\/(\d+)$/)
      if (jobMatch) return Promise.resolve(jobResponse(Number(jobMatch[1]), 'succeeded'))
      const deleteMatch = path.match(/^\/api\/audio-previews\/(\d+)$/)
      if (deleteMatch && init?.method === 'DELETE') {
        deletedJobs.push(Number(deleteMatch[1]))
        return Promise.resolve(emptyResponse())
      }
      if (path === '/api/audios/from-previews' && init?.method === 'POST') {
        publishBody = JSON.parse(String(init.body))
        return Promise.resolve(jsonResponse(publishedAudio(8), 201))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.get('#audio-title').setValue('Dialogue practice')
    await wrapper.get('#speaker-name-1').setValue('Woman')
    await wrapper.get('#turn-text-1').setValue('First line.')
    await button(wrapper, 'Add speaker').trigger('click')
    await wrapper.get('#speaker-name-2').setValue('Man')
    await wrapper.get('#speaker-voice-2').setValue('3')
    await button(wrapper, 'Add turn').trigger('click')
    await wrapper.get('#turn-speaker-2').setValue('2')
    await wrapper.get('#turn-text-2').setValue('Second line.')

    await wrapper.findAll('button').find((item) => item.text() === 'Generate preview')?.trigger('click')
    await flushPromises()
    expect(previewBodies).toEqual([
      { voiceId: 2, speakerDisplayName: 'Woman', text: 'First line.' },
    ])
    expect(wrapper.findAll('audio')).toHaveLength(1)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(previewBodies).toHaveLength(2)
    expect(button(wrapper, 'Publish').exists()).toBe(true)
    expect(wrapper.findAll('audio')).toHaveLength(2)

    await wrapper.get('button[aria-label="Move turn 2 up"]').trigger('click')
    expect(button(wrapper, 'Publish').exists()).toBe(true)
    await wrapper.get('#turn-text-1').setValue('Changed first line.')
    expect(wrapper.text()).toContain('Preview is out of date')
    expect(button(wrapper, 'Generate audio').exists()).toBe(true)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(previewBodies).toHaveLength(3)
    expect(deletedJobs).toContain(10)
    expect(button(wrapper, 'Publish').exists()).toBe(true)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(publishBody).toEqual({
      title: 'Dialogue practice',
      utterances: [
        {
          previewJobId: 11,
          voiceId: 3,
          speakerDisplayName: 'Man',
          text: 'Second line.',
        },
        {
          previewJobId: 12,
          voiceId: 2,
          speakerDisplayName: 'Woman',
          text: 'Changed first line.',
        },
      ],
      tagIds: [],
      visibility: 'private',
    })
    expect(wrapper.get('a[href="/audio/8"]').attributes('href')).toBe('/audio/8')
    wrapper.unmount()
  })

  it('keeps successful sibling previews when one turn fails', async () => {
    let nextJobId = 20
    const submittedJobs: number[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/audio-previews' && init?.method === 'POST') {
        const jobId = nextJobId++
        submittedJobs.push(jobId)
        return Promise.resolve(jsonResponse({ jobId, contentDigest: 'b'.repeat(64) }, 202))
      }
      const jobMatch = path.match(/^\/api\/jobs\/(\d+)$/)
      if (jobMatch) {
        const jobId = Number(jobMatch[1])
        return Promise.resolve(jobResponse(jobId, jobId === 21 ? 'failed' : 'succeeded'))
      }
      if (path.match(/^\/api\/audio-previews\/\d+$/) && init?.method === 'DELETE') {
        return Promise.resolve(emptyResponse())
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.get('#speaker-name-1').setValue('Woman')
    await wrapper.get('#turn-text-1').setValue('First line.')
    await button(wrapper, 'Add turn').trigger('click')
    await wrapper.get('#turn-text-2').setValue('Second line.')

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.findAll('audio')).toHaveLength(1)
    expect(wrapper.text()).toContain('Preview synthesis failed')
    expect(submittedJobs).toEqual([20, 21])

    const failedTurn = wrapper.findAll('li').find((item) => item.text().includes('Preview synthesis failed'))
    await failedTurn?.findAll('button').find((item) => item.text() === 'Regenerate preview')?.trigger('click')
    await flushPromises()
    expect(submittedJobs).toEqual([20, 21, 22])
    expect(wrapper.findAll('audio')).toHaveLength(2)
    expect(button(wrapper, 'Publish').exists()).toBe(true)
    wrapper.unmount()
  })
})
