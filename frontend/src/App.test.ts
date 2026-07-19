import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import App from './App.vue'
import { createAppRouter } from './router'
import { useAuthStore } from './stores/auth'


describe('App', () => {
  it('renders the application shell and a frontend 404 route', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().loaded = true
    const router = createAppRouter(createMemoryHistory())
    await router.push('/missing-route')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router],
      },
    })

    expect(wrapper.text()).toContain('Listening Studio')
    expect(wrapper.text()).toContain('Page not found')
    expect(wrapper.get('a[href="/"]').text()).toContain('Listening Studio')
    expect(wrapper.find('a[href="/audio"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/create"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/manage"]').exists()).toBe(false)

    useAuthStore().setCurrentUser({
      userId: 'TeacherOne',
      username: 'Teacher One',
      locale: 'en',
      profileComplete: true,
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.get('a[href="/create"]').text()).toBe('Create')
    expect(wrapper.get('a[href="/manage"]').text()).toBe('Manage')
  })
})
