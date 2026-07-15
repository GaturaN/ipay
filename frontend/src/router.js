import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '@/stores/session'

// A sales member's home is their own book — the driver page's data would only refuse them.
const salesHome = () => (window.sales_only ? { name: 'Sales' } : true)

const routes = [
  {
    path: '/',
    name: 'Collect',
    component: () => import('@/pages/Collect.vue'),
    beforeEnter: salesHome,
  },
  {
    // (.*) so customer ids containing '/' (real in this data) match into one param.
    path: '/customer/:customer(.*)',
    name: 'Customer',
    component: () => import('@/pages/CustomerDetail.vue'),
  },
  {
    path: '/internal',
    name: 'Internal',
    component: () => import('@/pages/InternalCollect.vue'),
  },
  {
    path: '/internal/customer/:customer(.*)',
    name: 'InternalCustomer',
    component: () => import('@/pages/InternalCustomerDetail.vue'),
  },
  {
    path: '/sales',
    name: 'Sales',
    component: () => import('@/pages/SalesCollect.vue'),
  },
  {
    path: '/sales/customer/:customer(.*)',
    name: 'SalesCustomer',
    component: () => import('@/pages/SalesCustomerDetail.vue'),
  },
  {
    path: '/request/:name',
    name: 'Request',
    component: () => import('@/pages/RequestDetail.vue'),
  },
  // Unmatched URLs (typo, stale bookmark, mis-decoded path) land on the list, never blank.
  {
    path: '/:pathMatch(.*)*',
    redirect: () => (window.sales_only ? { name: 'Sales' } : { name: 'Collect' }),
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
