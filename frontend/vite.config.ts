import vue from '@vitejs/plugin-vue'
import { configDefaults, defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

const backendTarget = process.env.VITE_BACKEND_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': backendTarget,
      '/auth': backendTarget,
      '/health': backendTarget,
      '/media': backendTarget,
    },
  },
  test: {
    environment: 'jsdom',
    clearMocks: true,
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})
