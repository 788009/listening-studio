import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AudioQuestion } from '@/api/audios'
import ExamQuestionsDisplay from './ExamQuestionsDisplay.vue'

const questions: AudioQuestion[] = Array.from({ length: 6 }, (_, index) => ({
  id: index + 1,
  prompt: `Question ${index + 1}`,
  correctAnswers: [`Correct ${index + 1}`],
  incorrectAnswers: [`Incorrect ${index + 1}A`, `Incorrect ${index + 1}B`],
  position: index,
}))

describe('ExamQuestionsDisplay', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('renders randomized options and groups answer keys in rows of five', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const wrapper = mount(ExamQuestionsDisplay, {
      props: { title: 'Practice', questions },
    })

    const blocks = wrapper.findAll('pre')
    expect(blocks[0]?.text()).toContain('1. Question 1')
    expect(blocks[0]?.text()).toContain('A. Incorrect 1A')
    expect(blocks[0]?.text()).toContain('B. Incorrect 1B')
    expect(blocks[0]?.text()).toContain('C. Correct 1')
    expect(blocks[1]?.text()).toBe('CCCCC\nC')

    await wrapper.get('button:last-child').trigger('click')
    expect(wrapper.findAll('pre')[1]?.text()).toBe('BBBBB\nB')
  })

  it('copies both the question and answer sections', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(ExamQuestionsDisplay, {
      props: { title: 'Practice', questions: questions.slice(0, 1) },
    })

    await wrapper.get('button').trigger('click')

    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('Questions\n1. Question 1'),
    )
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('\n\nAnswers\n'))
  })
})
