import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { usePreferencesStore } from './preferences'

describe('preferences store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('applies and persists explicit light and dark themes', () => {
    const preferences = usePreferencesStore()

    preferences.setTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('listening-studio-theme')).toBe('dark')

    preferences.toggleTheme()
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('listening-studio-theme')).toBe('light')
  })
})
