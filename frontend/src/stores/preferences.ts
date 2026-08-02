import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  matchLocale,
  setLocale,
  type SupportedLocale,
  useI18n,
} from '@/i18n'

export type ThemePreference = 'light' | 'dark'

const themeStorageKey = 'listening-studio-theme'
const languageStorageKey = 'listening-studio-language'

function initialTheme(): ThemePreference {
  const stored = localStorage.getItem(themeStorageKey)
  if (stored === 'light' || stored === 'dark') return stored
  if (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark'
  }
  return 'light'
}

function initialLanguage(): SupportedLocale {
  return matchLocale(localStorage.getItem(languageStorageKey)) ?? useI18n().locale.value
}

export const usePreferencesStore = defineStore('preferences', () => {
  const language = ref<SupportedLocale>(initialLanguage())
  const theme = ref<ThemePreference>(initialTheme())
  const resolvedTheme = computed(() => theme.value)

  function applyTheme(value: ThemePreference): void {
    document.documentElement.dataset.theme = value
    document.documentElement.classList.toggle('dark', value === 'dark')
    document.documentElement.style.colorScheme = value
  }

  function setTheme(value: ThemePreference): void {
    theme.value = value
    localStorage.setItem(themeStorageKey, value)
    applyTheme(value)
  }

  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  function setLanguage(value: unknown): void {
    const resolved = matchLocale(value) ?? 'en'
    language.value = resolved
    localStorage.setItem(languageStorageKey, resolved)
    setLocale(resolved)
  }

  applyTheme(theme.value)
  setLocale(language.value)

  return { language, theme, resolvedTheme, setLanguage, setTheme, toggleTheme }
})
