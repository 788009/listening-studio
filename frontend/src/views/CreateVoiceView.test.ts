import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import CreateVoiceView from './CreateVoiceView.vue'

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
      { path: '/voices/create', component: CreateVoiceView },
      { path: '/voice/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/voices/create')
  await router.isReady()
  return mount(CreateVoiceView, {
    global: { plugins: [createPinia(), router] },
  })
}

describe('create voice view', () => {
  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('submits the form and links to the completed voice', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path.startsWith('/api/voice-tags')) return Promise.resolve(jsonResponse([]))
      if (path === '/api/voices') {
        return Promise.resolve(jsonResponse({ voiceId: 8, jobId: 13 }, 202))
      }
      if (path === '/api/jobs/13') {
        return Promise.resolve(
          jsonResponse({
            id: 13,
            type: 'voice_upload',
            status: 'succeeded',
            progress: 100,
            inputSummary: { voiceId: 8 },
            result: { type: 'voice', id: 8 },
            cancelRequested: false,
            retryable: true,
            attemptCount: 1,
            createdAt: '2026-07-16T00:00:00Z',
            updatedAt: '2026-07-16T00:00:01Z',
          }),
        )
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.get('#voice-title').setValue('Classroom voice')
    const fileInput = wrapper.get('#voice-file')
    Object.defineProperty(fileInput.element, 'files', {
      configurable: true,
      value: [new File(['wav'], 'reference.wav', { type: 'audio/wav' })],
    })
    await fileInput.trigger('change')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Voice is ready')
    expect(wrapper.get('a[href="/voice/8"]').attributes('href')).toBe('/voice/8')
    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/voices')).toHaveLength(1)
    wrapper.unmount()
  })

  it('restores a failed task and shows its safe error summary', async () => {
    localStorage.setItem(
      'listening.voiceCreation',
      JSON.stringify({ jobId: 21, voiceId: 11 }),
    )
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input)
        if (path.startsWith('/api/voice-tags')) return Promise.resolve(jsonResponse([]))
        if (path === '/api/jobs/21') {
          return Promise.resolve(
            jsonResponse({
              id: 21,
              type: 'voice_upload',
              status: 'failed',
              progress: 80,
              inputSummary: { voiceId: 11 },
              errorSummary: 'Verify the reference WAV and try again.',
              cancelRequested: false,
              retryable: true,
              attemptCount: 1,
              createdAt: '2026-07-16T00:00:00Z',
              updatedAt: '2026-07-16T00:00:01Z',
            }),
          )
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )

    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Voice creation failed')
    expect(wrapper.get('[role="alert"]').text()).toContain('Verify the reference WAV')
    wrapper.unmount()
  })
})
