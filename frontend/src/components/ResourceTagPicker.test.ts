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
})
