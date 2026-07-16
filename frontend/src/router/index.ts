import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
    meta: { title: 'Library' },
  },
  {
    path: '/audio/:id',
    name: 'audio',
    component: () => import('@/views/AudioDetailView.vue'),
    meta: { title: 'Audio' },
  },
  {
    path: '/create',
    name: 'create',
    component: () => import('@/views/CreateView.vue'),
    meta: { title: 'Create', requiresTeacher: true },
  },
  {
    path: '/voices',
    name: 'voices',
    component: () => import('@/views/VoiceListView.vue'),
    meta: { title: 'Voices', requiresTeacher: true },
  },
  {
    path: '/voices/create',
    name: 'create-voice',
    component: () => import('@/views/CreateVoiceView.vue'),
    meta: { title: 'Create voice', requiresTeacher: true },
  },
  {
    path: '/voice/:id',
    name: 'voice',
    component: () => import('@/views/VoiceDetailView.vue'),
    meta: { title: 'Voice', requiresTeacher: true },
  },
  {
    path: '/setup-profile',
    name: 'setup-profile',
    component: () => import('@/views/ProfileSetupView.vue'),
    meta: { title: 'Set up profile' },
  },
  {
    path: '/user/:userId',
    name: 'user',
    component: () => import('@/views/UserView.vue'),
    meta: { title: 'Teacher profile' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: 'Page not found' },
  },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const appRouter = createRouter({ history, routes })
  appRouter.beforeEach(async (route) => {
    const auth = useAuthStore()
    await auth.loadCurrentUser()

    if (auth.isTeacher && !auth.profileComplete && route.name !== 'setup-profile') {
      return { name: 'setup-profile' }
    }
    if (route.name === 'setup-profile' && (!auth.isTeacher || auth.profileComplete)) {
      return { name: 'library' }
    }
    if (route.meta.requiresTeacher && !auth.isTeacher) {
      return { name: 'library' }
    }
    return true
  })
  appRouter.afterEach((route) => {
    const title = typeof route.meta.title === 'string' ? route.meta.title : 'Listening Studio'
    document.title = `${title} | Listening Studio`
  })
  return appRouter
}

export const router = createAppRouter()
