import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import RegisterView from './views/RegisterView.vue'
import DashboardView from './views/DashboardView.vue'
import { useAuth } from './stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/register', component: RegisterView, meta: { public: true } },
    { path: '/dashboard', component: DashboardView },
  ],
})

router.beforeEach((to) => {
  const { token } = useAuth()
  if (!to.meta.public && !token.value) return '/login'
  if (to.meta.public && token.value) return '/dashboard'
})

export default router
