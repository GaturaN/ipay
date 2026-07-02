import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '@/stores/session'

const routes = [
  {
    path: '/',
    name: 'Collect',
    component: () => import('@/pages/Collect.vue'),
  },
  {
    path: '/customer/:customer',
    name: 'Customer',
    component: () => import('@/pages/CustomerDetail.vue'),
  },
  {
    path: '/internal',
    name: 'Internal',
    component: () => import('@/pages/InternalCollect.vue'),
  },
  {
    path: '/internal/customer/:customer',
    name: 'InternalCustomer',
    component: () => import('@/pages/InternalCustomerDetail.vue'),
  },
  {
    path: '/request/:name',
    name: 'Request',
    component: () => import('@/pages/RequestDetail.vue'),
  },
]

// History base matches the mount route in hooks.py (/collect), so deep links and
// refreshes resolve to the SPA rather than a 404.
const router = createRouter({
  history: createWebHistory('/collect'),
  routes,
})

// Guard against navigating the app without a session (e.g. it expired mid-use);
// the server also redirects guests before the SPA ever loads.
router.beforeEach(() => {
  if (!useSession().isLoggedIn) {
    window.location.href = '/login?redirect-to=/collect'
    return false
  }
})

export default router
