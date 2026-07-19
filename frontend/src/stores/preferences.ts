import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type ThemePreference = 'light' | 'dark'

const storageKey = 'listening-studio-theme'

function initialTheme(): ThemePreference {
  const stored = localStorage.getItem(storageKey)
  if (stored === 'light' || stored === 'dark') return stored
  if (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

export const usePreferencesStore = defineStore('preferences', () => {
  const language = ref('en')
  const theme = ref<ThemePreference>(initialTheme())
  const resolvedTheme = computed(() => theme.value)

  function applyTheme(value: ThemePreference): void {
    document.documentElement.dataset.theme = value
    document.documentElement.classList.toggle('dark', value === 'dark')
    document.documentElement.style.colorScheme = value
  }

  function setTheme(value: ThemePreference): void {
    theme.value = value
    localStorage.setItem(storageKey, value)
    applyTheme(value)
  }

  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  function setLanguage(value: string) {
    language.value = value
  }

  applyTheme(theme.value)

  return { language, theme, resolvedTheme, setLanguage, setTheme, toggleTheme }
})
