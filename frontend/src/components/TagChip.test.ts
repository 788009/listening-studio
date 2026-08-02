import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import TagChip from './TagChip.vue'

describe('TagChip', () => {
  it('renders a typed tag as a searchable chip link', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/audio', component: { template: '<div />' } }],
    })
    await router.push('/audio')
    const wrapper = mount(TagChip, {
      props: {
        label: 'climate change',
        secondaryLabel: '@TeacherOne',
        typeLabel: 'Topic',
        to: { path: '/audio', query: { q: 'topic:climate_change' } },
      },
      global: { plugins: [router] },
    })

    expect(wrapper.get('a').classes()).toContain('tag-chip')
    expect(wrapper.text()).toContain('Topic')
    expect(wrapper.text()).toContain('@TeacherOne')
    expect(wrapper.findAll('span')[2]?.classes()).toContain('text-muted')
    expect(wrapper.get('a').attributes('href')).toBe('/audio?q=topic:climate_change')
  })

  it('exposes a selected removable chip as a button', async () => {
    const wrapper = mount(TagChip, {
      props: { label: 'female', selected: true, removable: true },
    })

    expect(wrapper.get('button').classes()).toContain('tag-chip-selected')
    expect(wrapper.get('button').attributes('title')).toBe('Remove tag')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('activate')).toHaveLength(1)
  })
})
