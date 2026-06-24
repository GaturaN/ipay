import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Collect',
    component: () => import('@/pages/Collect.vue'),
  },
]

// History base matches the mount route in hooks.py (/collect), so deep links and
// refreshes resolve to the SPA rather than a 404.
export default createRouter({
  history: createWebHistory('/collect'),
  routes,
})
