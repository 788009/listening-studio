import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePreferencesStore = defineStore('preferences', () => {
  const language = ref('en')

  function setLanguage(value: string) {
    language.value = value
  }

  return { language, setLanguage }
})
