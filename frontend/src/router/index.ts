import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: 'Home' },
  },
  {
    path: '/audio',
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
    path: '/generate',
    name: 'generate',
    component: () => import('@/views/GenerationBatchView.vue'),
    meta: { title: 'Corpus generation', requiresTeacher: true },
  },
  {
    path: '/generate/:id',
    name: 'generation-batch',
    component: () => import('@/views/GenerationBatchView.vue'),
    meta: { title: 'Generation batch', requiresTeacher: true },
  },
  {
    path: '/papers/new',
    name: 'paper-create',
    component: () => import('@/views/PaperComposerView.vue'),
    meta: { title: 'Assemble paper', requiresTeacher: true },
  },
  {
    path: '/manage',
    name: 'resource-management',
    component: () => import('@/views/ResourceManagementView.vue'),
    meta: { title: 'Resource management', requiresTeacher: true },
  },
  {
    path: '/admin/users',
    name: 'user-roles',
    component: () => import('@/views/UserRolesView.vue'),
    meta: { title: 'User roles', requiresSuperAdmin: true },
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
      return { name: 'home' }
    }
    if (route.meta.requiresTeacher && !auth.isTeacher) {
      return { name: 'home' }
    }
    if (route.meta.requiresSuperAdmin && !auth.isSuperAdmin) {
      return { name: 'home' }
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
