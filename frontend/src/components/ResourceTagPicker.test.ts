import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ResourceTagPicker from './ResourceTagPicker.vue'

describe('ResourceTagPicker', () => {
  it('renders selected tags below the search controls', () => {
    const wrapper = mount(ResourceTagPicker, {
      props: {
        label: 'Topics',
        type: 'topic',
        tags: [
          {
            id: 1,
            type: 'topic',
            englishValue: 'Climate_Change',
            displayValue: 'climate_change',
            fullTag: 'topic:Climate_Change',
            translations: [],
          },
        ],
        selectedIds: [1],
      },
    })

    const orderedElements = wrapper.findAll('input, .tag-chip-selected')
    expect(orderedElements).toHaveLength(2)
    expect(orderedElements[0]?.element.tagName).toBe('INPUT')
    expect(orderedElements[1]?.classes()).toContain('tag-chip-selected')
  })

  it('ranks direct prefixes before earlier dictionary entries', async () => {
    const wrapper = mount(ResourceTagPicker, {
      props: {
        label: 'Categories',
        type: 'category',
        tags: [
          {
            id: 1,
            type: 'category',
            englishValue: 'conversation',
            displayValue: 'conversation',
            fullTag: 'category:conversation',
            translations: [],
          },
          {
            id: 2,
            type: 'category',
            englishValue: 'single',
            displayValue: 'single',
            fullTag: 'category:single',
            translations: [],
          },
        ],
        selectedIds: [],
      },
    })

    await wrapper.get('input').setValue('s')
    const options = wrapper.findAll('[role="option"]')
    expect(options.map((option) => option.text())).toEqual(['single', 'conversation'])
    expect(wrapper.find('.tag-chip').exists()).toBe(false)

    await wrapper.get('input').setValue('ca')
    expect(wrapper.findAll('[role="option"]')).toHaveLength(0)
    await wrapper.get('input').setValue('category:s')
    expect(wrapper.findAll('[role="option"]').map((option) => option.text())).toEqual([
      'single',
    ])
  })

  it('selects the best match with Enter and keeps the outer form idle', async () => {
    const wrapper = mount(ResourceTagPicker, {
      props: {
        label: 'Categories',
        type: 'category',
        tags: [
          {
            id: 1,
            type: 'category',
            englishValue: 'conversation',
            displayValue: 'conversation',
            fullTag: 'category:conversation',
            translations: [],
          },
          {
            id: 2,
            type: 'category',
            englishValue: 'single',
            displayValue: 'single',
            fullTag: 'category:single',
            translations: [],
          },
        ],
        selectedIds: [],
      },
    })

    await wrapper.get('input').setValue('s')
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('select')).toEqual([[2]])
    expect(wrapper.get('input').element).toHaveProperty('value', '')
  })
})
