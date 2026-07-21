import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import UserRolesView from './UserRolesView.vue'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('UserRolesView', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists roles and updates only assignable user roles', async () => {
    const users = [
      {
        userId: 'RootTeacher',
        username: 'Root Teacher',
        role: 'super_admin',
        createdAt: '2026-07-20T00:00:00Z',
      },
      {
        userId: 'TeacherOne',
        username: 'Teacher One',
        role: 'user',
        createdAt: '2026-07-21T00:00:00Z',
      },
    ]
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ items: users, page: 1, pageSize: 25, total: 2 }))
      .mockResolvedValueOnce(jsonResponse({ ...users[1], role: 'admin' }))
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(UserRolesView)
    await flushPromises()

    expect(wrapper.text()).toContain('Root Teacher')
    expect(wrapper.text()).toContain('Super Admin')
    expect(wrapper.findAll('select')).toHaveLength(1)
    await wrapper.get('select').setValue('admin')
    const saveButton = wrapper.findAll('button').find((button) => button.text() === 'Save')
    await saveButton?.trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/users?page=1&pageSize=25')
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/users/TeacherOne/role')
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ role: 'admin' }),
    })
    expect(wrapper.get('select').element).toHaveProperty('value', 'admin')
  })
})
