import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import AuthorLink from './AuthorLink.vue'

async function mountAuthorLink(username: string | null) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/user/:userId', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  return mount(AuthorLink, {
    props: { author: { userId: 'TeacherOne', username } },
    global: { plugins: [router] },
  })
}

describe('AuthorLink', () => {
  it('links only the display name and shows the muted user ID as text', async () => {
    const wrapper = await mountAuthorLink('Teacher One')

    expect(wrapper.get('a').attributes('href')).toBe('/user/TeacherOne')
    expect(wrapper.get('a').text()).toBe('Teacher One')
    expect(wrapper.findAll('a')).toHaveLength(1)
    expect(wrapper.findAll('span')[1]?.text()).toBe('@TeacherOne')
    expect(wrapper.findAll('span')[1]?.classes()).toContain('text-muted')
  })

  it('falls back to the user ID when no display name is set', async () => {
    const wrapper = await mountAuthorLink(null)

    expect(wrapper.get('a').text()).toBe('TeacherOne')
    expect(wrapper.findAll('span')[1]?.text()).toBe('@TeacherOne')
  })
})
