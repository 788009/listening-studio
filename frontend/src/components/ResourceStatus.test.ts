import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ResourceStatus from './ResourceStatus.vue'

describe('ResourceStatus', () => {
  it('announces dynamic states and disables motion when requested', () => {
    const wrapper = mount(ResourceStatus, { props: { status: 'processing' } })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.text()).toBe('Processing')
    expect(wrapper.get('svg').classes()).toContain('motion-reduce:animate-none')
  })
})
