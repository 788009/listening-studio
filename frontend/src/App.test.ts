import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import App from './App.vue'
import { createAppRouter } from './router'


describe('App', () => {
  it('renders the application shell and a frontend 404 route', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/missing-route')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [createPinia(), router],
      },
    })

    expect(wrapper.text()).toContain('Listening Studio')
    expect(wrapper.text()).toContain('Page not found')
    expect(wrapper.get('a[href="/"]').text()).toContain('Listening Studio')
  })
})
