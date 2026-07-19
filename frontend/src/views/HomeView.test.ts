import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import HomeView from './HomeView.vue'

const audio = {
  id: 8,
  author: { userId: 'TeacherOne', username: 'Teacher One' },
  title: 'A calm morning briefing',
  text: 'Transcript',
  sourceType: 'single_speaker',
  status: 'ready',
  visibility: 'public',
  durationSeconds: 74,
  sampleRate: 24000,
  tags: [],
  utterances: [],
}

describe('home view', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows recent public audio and sends searches to the audio library', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [audio], page: 1, pageSize: 4, total: 1 }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: HomeView },
        { path: '/audio', component: { template: '<div />' } },
        { path: '/audio/:id', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    const wrapper = mount(HomeView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('A calm morning briefing')
    expect(wrapper.get('a[href="/audio/8"]').attributes('href')).toBe('/audio/8')
    await wrapper.get('#home-search').setValue('climate change')
    await wrapper.get('form[role="search"]').trigger('submit')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/audio?q=climate+change')
  })
})
