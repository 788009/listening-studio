import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
    meta: { title: 'Library' },
  },
  {
    path: '/create',
    name: 'create',
    component: () => import('@/views/CreateView.vue'),
    meta: { title: 'Create' },
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
  appRouter.afterEach((route) => {
    const title = typeof route.meta.title === 'string' ? route.meta.title : 'Listening Studio'
    document.title = `${title} | Listening Studio`
  })
  return appRouter
}

export const router = createAppRouter()
