import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ActiveJobProgress from './ActiveJobProgress.vue'

const stages = [
  { threshold: 5, label: 'Preparing audio generation' },
  { threshold: 20, label: 'Generating speech' },
  { threshold: 82, label: 'Processing generated audio' },
  { threshold: 88, label: 'Saving audio' },
]

describe('ActiveJobProgress', () => {
  it('shows the current stage and keeps a running task visibly active', () => {
    const wrapper = mount(ActiveJobProgress, {
      props: {
        progress: 20,
        queued: false,
        queuedLabel: 'Waiting for processing',
        stages,
        taskLabel: 'Task 13',
        progressLabel: 'Audio generation progress',
      },
    })

    expect(wrapper.text()).toContain('Generating speech')
    expect(wrapper.text()).toContain('Stage 2 of 4')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('20')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuetext')).toBe(
      'Generating speech',
    )
    expect(wrapper.find('.job-progress-activity').exists()).toBe(true)
    expect(wrapper.get('svg').classes()).toContain('motion-reduce:animate-none')
  })

  it('shows queued work without implying that model processing has started', () => {
    const wrapper = mount(ActiveJobProgress, {
      props: {
        progress: 0,
        queued: true,
        queuedLabel: 'Waiting for processing',
        stages,
        taskLabel: 'Task 13',
        progressLabel: 'Audio generation progress',
      },
    })

    expect(wrapper.text()).toContain('Waiting for processing')
    expect(wrapper.text()).toContain('Stage 0 of 4')
    expect(wrapper.find('.job-progress-activity').exists()).toBe(false)
    expect(wrapper.find('svg').exists()).toBe(false)
  })
})
