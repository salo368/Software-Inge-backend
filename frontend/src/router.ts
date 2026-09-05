import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import LoginView from './views/LoginView.vue'
import RegisterView from './views/RegisterView.vue'
import DashboardView from './views/DashboardView.vue'
import CdtView from './views/CdtView.vue'
import { useAuth } from './stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { public: true } },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/register', name: 'register', component: RegisterView, meta: { public: true } },
    { path: '/dashboard', name: 'dashboard', component: DashboardView },
    { path: '/cdt/:id', name: 'cdt', component: CdtView },
  ],
})

router.beforeEach((to) => {
  const { token } = useAuth()
  // Ruta privada sin token: al login
  if (!to.meta.public && !token.value) return '/login'
  // Login/register con sesion activa: al dashboard (home siempre accesible)
  if ((to.name === 'login' || to.name === 'register') && token.value) return '/dashboard'
})

export default router
