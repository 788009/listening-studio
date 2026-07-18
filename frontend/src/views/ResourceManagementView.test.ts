import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import type { ManagedResource } from '@/api/resourceManagement'
import ResourceManagementView from './ResourceManagementView.vue'

const voice: ManagedResource = {
  id: 1,
  kind: 'voice',
  title: 'Calm voice',
  status: 'ready',
  visibility: 'private',
  tags: [{ id: 4, type: 'gender', value: 'female' }],
  createdAt: '2026-01-10T00:00:00Z',
  references: [],
  canDelete: true,
}

const failedVoice: ManagedResource = {
  ...voice,
  id: 2,
  title: 'Failed voice',
  status: 'failed',
}

const referencedVoice: ManagedResource = {
  ...voice,
  id: 3,
  title: 'Referenced voice',
  references: [{ type: 'generation_batch', count: 2 }],
  canDelete: false,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: status === 204 ? undefined : { 'Content-Type': 'application/json' },
  })
}

function listResponse(
  items: ManagedResource[],
  page = 1,
  total = items.length,
): Response {
  return jsonResponse({ items, page, pageSize: 20, total })
}

function optionResponse(path: string): Response | null {
  if (path.startsWith('/api/voice-tags')) {
    return jsonResponse([
      {
        id: 4,
        type: 'gender',
        displayValue: 'Female',
        englishValue: 'female',
        fullTag: 'gender:female',
        translations: [],
      },
    ])
  }
  if (path.startsWith('/api/audio-tags')) return jsonResponse([])
  return null
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/manage', component: ResourceManagementView },
      { path: '/voice/:id', component: { template: '<div />' } },
      { path: '/audio/:id', component: { template: '<div />' } },
      { path: '/generate/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/manage')
  await router.isReady()
  return mount(ResourceManagementView, {
    global: { plugins: [createPinia(), router] },
  })
}

describe('resource management view', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('preserves selection across pages and clears it when filters change', async () => {
    const managementRequests: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input)
        const option = optionResponse(path)
        if (option) return Promise.resolve(option)
        if (path.startsWith('/api/resource-management?')) {
          managementRequests.push(path)
          const secondPage = path.includes('page=2')
          return Promise.resolve(
            listResponse(secondPage ? [failedVoice] : [voice], secondPage ? 2 : 1, 25),
          )
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const wrapper = await mountView()
    await flushPromises()

    await wrapper.get('input[aria-label="Select Calm voice"]').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('Next'))?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('1 selected across pages')
    await wrapper.get('input[aria-label="Select Failed voice"]').setValue(true)
    expect(wrapper.text()).toContain('2 selected across pages')

    await wrapper.get('#management-status').setValue('failed')
    await wrapper.get('#management-visibility').setValue('private')
    await wrapper.get('#management-created-from').setValue('2026-01-01')
    await wrapper.get('#management-created-to').setValue('2026-01-31')
    const genderLabel = wrapper.findAll('label').find((label) => label.text().includes('Gender: Female'))
    await genderLabel?.get('input').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).not.toContain('selected across pages')
    const filteredPath = managementRequests[managementRequests.length - 1] ?? ''
    expect(filteredPath).toContain('status=failed')
    expect(filteredPath).toContain('visibility=private')
    expect(filteredPath).toContain('tagId=4')
    expect(filteredPath).toContain('created_from=2026-01-01')
    expect(filteredPath).toContain('created_before=2026-02-01')
    wrapper.unmount()
  })

  it('shows detailed bulk outcomes and keeps unsuccessful items selected', async () => {
    let bulkBody: unknown
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const option = optionResponse(path)
        if (option) return Promise.resolve(option)
        if (path.startsWith('/api/resource-management?')) {
          return Promise.resolve(listResponse([voice, failedVoice, referencedVoice]))
        }
        if (path === '/api/resource-management/bulk-update') {
          bulkBody = JSON.parse(String(init?.body))
          return Promise.resolve(
            jsonResponse({
              items: [
                { id: 1, outcome: 'success', message: 'Resource updated' },
                { id: 2, outcome: 'conflict', message: 'Only ready resources can be public' },
                { id: 3, outcome: 'failed', message: 'Resource is unavailable' },
              ],
              successCount: 1,
              conflictCount: 1,
              failedCount: 1,
            }),
          )
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const wrapper = await mountView()
    await flushPromises()

    for (const title of ['Calm voice', 'Failed voice', 'Referenced voice']) {
      await wrapper.get(`input[aria-label="Select ${title}"]`).setValue(true)
    }
    await wrapper.get('#bulk-visibility').setValue('public')
    await wrapper.findAll('button').find((button) => button.text() === 'Apply changes')?.trigger('click')
    await flushPromises()

    expect(bulkBody).toEqual({
      kind: 'voice',
      resourceIds: [1, 2, 3],
      visibility: 'public',
    })
    expect(wrapper.text()).toContain('1 succeeded, 1 conflicts, 1 failed')
    expect(wrapper.text()).toContain('2: Only ready resources can be public')
    expect(wrapper.text()).toContain('2 selected across pages')
    expect(wrapper.text()).toContain('Referenced by 2 generation batch')
    expect(
      wrapper.get('button[title="Referenced resources cannot be deleted"]').attributes('disabled'),
    ).toBeDefined()
    expect(wrapper.find('table').exists()).toBe(false)
    wrapper.unmount()
  })

  it('switches all resource tabs and confirms deletion', async () => {
    const kinds: string[] = []
    let deleted = false
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        const option = optionResponse(path)
        if (option) return Promise.resolve(option)
        if (path.startsWith('/api/resource-management?')) {
          const value = new URL(path, 'http://test').searchParams.get('kind') ?? ''
          kinds.push(value)
          return Promise.resolve(listResponse(value === 'voice' && !deleted ? [voice] : []))
        }
        if (path === '/api/voices/1' && init?.method === 'DELETE') {
          deleted = true
          return Promise.resolve(jsonResponse(null, 204))
        }
        throw new Error(`Unexpected request: ${path}`)
      }),
    )
    const wrapper = await mountView()
    await flushPromises()

    for (const label of ['My audios', 'Generation batches', 'Papers', 'My voices']) {
      await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === label)?.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('button').find((button) => button.text() === 'Delete')?.trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('Delete Calm voice')
    await wrapper
      .get('[role="dialog"]')
      .findAll('button')
      .find((button) => button.text() === 'Delete')
      ?.trigger('click')
    await flushPromises()

    expect(kinds).toEqual(
      expect.arrayContaining(['voice', 'audio', 'generation_batch', 'paper']),
    )
    expect(deleted).toBe(true)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
