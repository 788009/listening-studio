import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { setLocale } from '@/i18n'
import { useListeningDraftsStore } from '@/stores/listeningDrafts'
import { useAuthStore, type UserRole } from '@/stores/auth'
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

async function mountView(role: UserRole | null = null, path = '/create?voice=2') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  if (role) {
    auth.setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher',
      locale: 'en',
      profileComplete: true,
      role,
    })
  } else {
    auth.loaded = true
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/create', component: CreateView },
      { path: '/audio/:id', component: { template: '<div />' } },
      { path: '/voices/create', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  return mount({ template: '<router-view />' }, {
    global: { plugins: [pinia, router] },
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
    setLocale('en')
  })

  it('uses the localized default speaker name', async () => {
    setLocale('zh-CN')
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

    expect(wrapper.get('#speaker-name-1').element).toHaveProperty('value', '说话人 1')
    expect(wrapper.get('#turn-speaker-1').text()).toContain('说话人 1')
    wrapper.unmount()
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
    expect(wrapper.get('#speaker-name-1').element).toHaveProperty('value', 'Speaker 1')
    expect(wrapper.get('#turn-speaker-1').text()).toContain('Speaker 1')
    expect(button(wrapper, 'Generate preview').exists()).toBe(true)
    expect(button(wrapper, 'Generate audio').exists()).toBe(true)
    expect(wrapper.find('input[type="file"]').exists()).toBe(false)
    expect(wrapper.get('input[type="checkbox"]').element).toHaveProperty(
      'checked',
      true,
    )
    wrapper.unmount()
  })

  it('prefills every editable field from a public audio creation draft', async () => {
    const topic = {
      id: 4,
      type: 'topic',
      englishValue: 'climate',
      displayValue: 'Climate',
      fullTag: 'topic:climate',
      translations: [],
    }
    const category = {
      id: 5,
      type: 'category',
      englishValue: 'long',
      displayValue: 'Long',
      fullTag: 'category:long',
      translations: [],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input)
        if (path.startsWith('/api/voices')) return Promise.resolve(jsonResponse(voices))
        if (path.includes('type=topic')) return Promise.resolve(jsonResponse([topic]))
        if (path.includes('type=category')) return Promise.resolve(jsonResponse([category]))
        if (path === '/api/audios/5/creation-draft') {
          return Promise.resolve(jsonResponse({
            sourceAudioId: 5,
            title: 'Climate briefing 2',
            text: 'First line.\nSecond line.\nThird line.',
            utterances: [
              { voiceId: 2, speakerDisplayName: 'Woman', text: 'First line.' },
              { voiceId: 3, speakerDisplayName: 'Student', text: 'Second line.' },
              { voiceId: 2, speakerDisplayName: 'Woman', text: 'Third line.' },
            ],
            tagIds: [4, 5],
            questions: [{
              prompt: 'Who spoke first?',
              correctAnswers: ['Woman'],
              incorrectAnswers: ['Student'],
            }],
          }))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    const wrapper = await mountView('user', '/create?fromAudio=5')
    await flushPromises()

    expect(wrapper.get('#audio-title').element).toHaveProperty('value', 'Climate briefing 2')
    expect(wrapper.findAll('[id^="speaker-name-"]')).toHaveLength(2)
    expect(wrapper.get('#speaker-name-1').element).toHaveProperty('value', 'Woman')
    expect(wrapper.get('#speaker-voice-1').element).toHaveProperty('value', '2')
    expect(wrapper.get('#speaker-name-2').element).toHaveProperty('value', 'Student')
    expect(wrapper.get('#speaker-voice-2').element).toHaveProperty('value', '3')
    expect(wrapper.get('#turn-text-1').element).toHaveProperty('value', 'First line.')
    expect(wrapper.get('#turn-text-2').element).toHaveProperty('value', 'Second line.')
    expect(wrapper.get('#turn-text-3').element).toHaveProperty('value', 'Third line.')
    expect(wrapper.get('#question-prompt-0').element).toHaveProperty('value', 'Who spoke first?')
    expect(wrapper.get('#question-0-correctAnswers-0').element).toHaveProperty('value', 'Woman')
    expect(wrapper.get('#question-0-incorrectAnswers-0').element).toHaveProperty('value', 'Student')
    expect(wrapper.text()).toContain('Climate')
    expect(wrapper.text()).toContain('Long')
    wrapper.unmount()
  })

  it('lets an admin upload and preview a turn audio file', async () => {
    let uploadBody: FormData | undefined
    let publishBody: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const options = optionsResponse(path)
        if (options) return Promise.resolve(options)
        if (path === '/api/audio-previews/upload' && init?.method === 'POST') {
          uploadBody = init.body as FormData
          return Promise.resolve(
            jsonResponse({ jobId: 77, contentDigest: 'd'.repeat(64) }, 201),
          )
        }
        if (path === '/api/audios/from-previews' && init?.method === 'POST') {
          publishBody = JSON.parse(String(init.body))
          return Promise.resolve(jsonResponse(publishedAudio(12), 201))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const wrapper = await mountView('admin')
    await flushPromises()
    const file = new File(['audio'], 'turn.mp3', { type: 'audio/mpeg' })
    const fileInput = wrapper.get('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', {
      value: [file],
      configurable: true,
    })
    await fileInput.trigger('change')
    await flushPromises()

    expect([...(uploadBody?.keys() ?? [])]).toEqual(['file'])
    expect(uploadBody?.get('file')).toBe(file)
    expect(wrapper.get('audio').attributes('src')).toBe('/media/audio-preview/77')
    expect(button(wrapper, 'Publish').exists()).toBe(true)

    await wrapper.get('#audio-title').setValue('Uploaded listening')
    await wrapper.get('#speaker-name-1').setValue('Narrator')
    await wrapper.get('#speaker-voice-1').setValue('3')
    await wrapper.get('#turn-text-1').setValue('Text entered after upload.')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(publishBody).toMatchObject({
      utterances: [
        {
          previewJobId: 77,
          voiceId: 3,
          speakerDisplayName: 'Narrator',
          text: 'Text entered after upload.',
        },
      ],
    })
    wrapper.unmount()
  })

  it('returns an uploaded turn to generated snapshot behavior after generation', async () => {
    let publishBody: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const options = optionsResponse(path)
        if (options) return Promise.resolve(options)
        if (path === '/api/audio-previews/upload' && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({ jobId: 80, contentDigest: 'e'.repeat(64) }, 201),
          )
        }
        if (path === '/api/audio-previews' && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({ jobId: 81, contentDigest: 'f'.repeat(64) }, 202),
          )
        }
        if (path === '/api/jobs/81') {
          return Promise.resolve(jobResponse(81, 'succeeded'))
        }
        if (path === '/api/audio-previews/80' && init?.method === 'DELETE') {
          return Promise.resolve(emptyResponse())
        }
        if (path === '/api/audios/from-previews' && init?.method === 'POST') {
          publishBody = JSON.parse(String(init.body))
          return Promise.resolve(jsonResponse(publishedAudio(13), 201))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const wrapper = await mountView('super_admin')
    await flushPromises()
    const fileInput = wrapper.get('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', {
      value: [new File(['audio'], 'turn.wav', { type: 'audio/wav' })],
      configurable: true,
    })
    await fileInput.trigger('change')
    await flushPromises()
    await wrapper.get('#audio-title').setValue('Generated replacement')
    await wrapper.get('#speaker-name-1').setValue('Woman')
    await wrapper.get('#turn-text-1').setValue('Generated text.')
    await button(wrapper, 'Regenerate preview').trigger('click')
    await flushPromises()

    await wrapper.get('#turn-text-1').setValue('Changed after generation.')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[role="dialog"]').text()).toContain(
      'Changes made after preview generation will be discarded',
    )
    expect(publishBody).toBeUndefined()
    wrapper.unmount()
  })

  it('keeps previews after edits and allows regeneration before publishing', async () => {
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
    await button(wrapper, 'Add question').trigger('click')
    await wrapper.get('#question-prompt-0').setValue('Who spoke first?')
    await wrapper.get('#question-0-correctAnswers-0').setValue('Man')
    await wrapper.get('#question-0-incorrectAnswers-0').setValue('Woman')

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
    expect(wrapper.text()).not.toContain('Preview is out of date')
    expect(wrapper.findAll('audio')).toHaveLength(2)
    expect(
      wrapper.findAll('button').filter((item) => item.text() === 'Regenerate preview'),
    ).toHaveLength(2)
    expect(button(wrapper, 'Publish').exists()).toBe(true)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain(
      'Changes made after preview generation will be discarded',
    )
    expect(publishBody).toBeUndefined()
    await wrapper.get('[role="dialog"]').findAll('button').find((item) => item.text() === 'Cancel')?.trigger('click')

    const changedTurn = wrapper.findAll('li').find((item) => item.find('#turn-text-1').exists())
    await changedTurn?.findAll('button').find((item) => item.text() === 'Regenerate preview')?.trigger('click')
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
      visibility: 'public',
      questions: [
        {
          prompt: 'Who spoke first?',
          correctAnswers: ['Man'],
          incorrectAnswers: ['Woman'],
        },
      ],
    })
    expect(wrapper.get('a[href="/audio/8"]').attributes('href')).toBe('/audio/8')
    wrapper.unmount()
  })

  it('publishes a renamed speaker without requiring regeneration', async () => {
    let publishBody: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const options = optionsResponse(path)
        if (options) return Promise.resolve(options)
        if (path === '/api/audio-previews' && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({ jobId: 29, contentDigest: 'c'.repeat(64) }, 202),
          )
        }
        if (path === '/api/jobs/29') {
          return Promise.resolve(jobResponse(29, 'succeeded'))
        }
        if (path === '/api/audios/from-previews' && init?.method === 'POST') {
          publishBody = JSON.parse(String(init.body))
          return Promise.resolve(jsonResponse(publishedAudio(9), 201))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.get('#audio-title').setValue('Renamed speaker')
    await wrapper.get('#speaker-name-1').setValue('Woman')
    await wrapper.get('#turn-text-1').setValue('Generated text.')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await wrapper.get('#speaker-name-1').setValue('Narrator')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(publishBody).toMatchObject({
      utterances: [
        {
          previewJobId: 29,
          voiceId: 2,
          speakerDisplayName: 'Narrator',
          text: 'Generated text.',
        },
      ],
    })
    wrapper.unmount()
  })

  it('confirms when selecting another speaker with the same voice', async () => {
    let publishBody: unknown
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const options = optionsResponse(path)
      if (options) return Promise.resolve(options)
      if (path === '/api/audio-previews' && init?.method === 'POST') {
        return Promise.resolve(
          jsonResponse({ jobId: 30, contentDigest: 'c'.repeat(64) }, 202),
        )
      }
      if (path === '/api/jobs/30') {
        return Promise.resolve(jobResponse(30, 'succeeded'))
      }
      if (path === '/api/audios/from-previews' && init?.method === 'POST') {
        publishBody = JSON.parse(String(init.body))
        return Promise.resolve(jsonResponse(publishedAudio(9), 201))
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.get('#audio-title').setValue('Snapshot practice')
    await wrapper.get('#speaker-name-1').setValue('Woman')
    await wrapper.get('#turn-text-1').setValue('Generated text.')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await button(wrapper, 'Add speaker').trigger('click')
    await wrapper.get('#speaker-name-2').setValue('Man')
    await wrapper.get('#turn-speaker-1').setValue('2')
    expect(wrapper.findAll('audio')).toHaveLength(1)
    expect(button(wrapper, 'Publish').exists()).toBe(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.text()).toContain('last generated audio')
    await dialog.findAll('button').find((item) => item.text() === 'Publish')?.trigger('click')
    await flushPromises()

    expect(publishBody).toEqual({
      title: 'Snapshot practice',
      utterances: [
        {
          previewJobId: 30,
          voiceId: 2,
          speakerDisplayName: 'Woman',
          text: 'Generated text.',
        },
      ],
      tagIds: [],
      visibility: 'public',
      questions: [],
    })
    expect(wrapper.get('a[href="/audio/9"]').attributes('href')).toBe('/audio/9')
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

  it('generates every draft preview before publishing and retains failed drafts', async () => {
    const previewBodies: unknown[] = []
    const publishBodies: unknown[] = []
    let nextJobId = 40
    let monologuePublishAttempts = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const options = optionsResponse(path)
        if (options) return Promise.resolve(options)
        if (path === '/api/audio-previews' && init?.method === 'POST') {
          previewBodies.push(JSON.parse(String(init.body)))
          const jobId = nextJobId++
          return Promise.resolve(
            jsonResponse({ jobId, contentDigest: 'd'.repeat(64) }, 202),
          )
        }
        const jobMatch = path.match(/^\/api\/jobs\/(\d+)$/)
        if (jobMatch) {
          return Promise.resolve(jobResponse(Number(jobMatch[1]), 'succeeded'))
        }
        if (path === '/api/audios/from-previews' && init?.method === 'POST') {
          const body = JSON.parse(String(init.body))
          publishBodies.push(body)
          if (body.title === 'Monologue draft') {
            monologuePublishAttempts += 1
            if (monologuePublishAttempts === 1) {
              return Promise.resolve(jsonResponse({ detail: 'Publish failed' }, 500))
            }
            return Promise.resolve(jsonResponse(publishedAudio(52), 201))
          }
          return Promise.resolve(jsonResponse(publishedAudio(51), 201))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/create', name: 'create', component: CreateView },
        { path: '/audio/:id', component: { template: '<div />' } },
        { path: '/voices/create', component: { template: '<div />' } },
      ],
    })
    const pinia = createPinia()
    const store = useListeningDraftsStore(pinia)
    store.setBatch({
      id: 7,
      jobId: 9,
      questionTypeCounts: { short_dialogue: 1, monologue: 1 },
      status: 'completed',
      progress: 100,
      tags: [
        { id: 4, type: 'topic', englishValue: 'travel' },
        { id: 5, type: 'category', englishValue: 'short' },
        { id: 6, type: 'category', englishValue: 'monologue' },
      ],
      speakerVoices: [],
      items: [
        {
          id: 1,
          position: 0,
          status: 'completed',
          attemptCount: 1,
          draft: {
            questionType: 'short_dialogue',
            title: 'Dialogue draft',
            utterances: [
              { speakerDisplayName: 'Man', voiceId: 2, text: 'First.' },
              { speakerDisplayName: 'Woman', voiceId: 3, text: 'Second.' },
            ],
            questions: [
              { prompt: 'Who?', correctAnswers: ['Man'], incorrectAnswers: ['Woman'] },
            ],
          },
        },
        {
          id: 2,
          position: 1,
          status: 'completed',
          attemptCount: 1,
          draft: {
            questionType: 'monologue',
            title: 'Monologue draft',
            utterances: [{ speakerDisplayName: 'Woman', voiceId: 3, text: 'Report.' }],
            questions: [
              { prompt: 'What?', correctAnswers: ['Report'], incorrectAnswers: ['Call'] },
            ],
          },
        },
      ],
      createdAt: '',
      updatedAt: '',
    })
    await router.push('/create?batch=7')
    await router.isReady()
    const wrapper = mount({ template: '<router-view />' }, {
      global: { plugins: [pinia, router] },
    })
    await flushPromises()

    expect(wrapper.get('#audio-title').element).toHaveProperty('value', 'Dialogue draft')
    expect(wrapper.text()).toContain('Draft 1 of 2')
    await wrapper.get('button[title="Next"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('#audio-title').element).toHaveProperty('value', 'Monologue draft')
    expect(button(wrapper, 'Generate all draft audio').exists()).toBe(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(previewBodies).toEqual([
      { voiceId: 2, speakerDisplayName: 'Man', text: 'First.' },
      { voiceId: 3, speakerDisplayName: 'Woman', text: 'Second.' },
      { voiceId: 3, speakerDisplayName: 'Woman', text: 'Report.' },
    ])
    expect(button(wrapper, 'Publish all drafts').exists()).toBe(true)
    expect(wrapper.findAll('audio')).toHaveLength(1)

    await wrapper.get('button[title="Previous"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('audio')).toHaveLength(2)
    await wrapper.get('button[title="Next"]').trigger('click')
    await wrapper.get('#turn-text-1').setValue('Edited report.')
    expect(wrapper.findAll('audio')).toHaveLength(1)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain(
      'Changes made after preview generation will be discarded for affected drafts',
    )
    await wrapper.get('[role="dialog"]').findAll('button').find((item) => item.text() === 'Publish')?.trigger('click')
    await flushPromises()

    expect(publishBodies).toHaveLength(2)
    expect(publishBodies[0]).toMatchObject({
      title: 'Dialogue draft',
      tagIds: [4, 5],
      visibility: 'public',
      utterances: [
        { previewJobId: 40, text: 'First.' },
        { previewJobId: 41, text: 'Second.' },
      ],
    })
    expect(publishBodies[1]).toMatchObject({
      title: 'Monologue draft',
      tagIds: [4, 6],
      utterances: [{ previewJobId: 42, text: 'Report.' }],
    })
    expect(store.drafts).toHaveLength(1)
    expect(wrapper.findAll('audio')).toHaveLength(1)
    expect(button(wrapper, 'Publish all drafts').exists()).toBe(true)

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    await wrapper.get('[role="dialog"]').findAll('button').find((item) => item.text() === 'Publish')?.trigger('click')
    await flushPromises()

    expect(publishBodies).toHaveLength(3)
    expect(publishBodies[2]).toMatchObject({
      title: 'Monologue draft',
      utterances: [{ previewJobId: 42, text: 'Report.' }],
    })
    expect(wrapper.find('a[href="/audio/51"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/audio/52"]').exists()).toBe(true)
    expect(store.drafts).toHaveLength(0)
    wrapper.unmount()
  })
})
