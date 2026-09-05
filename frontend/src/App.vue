<script setup lang="ts">
import { RouterView, RouterLink, useRouter } from 'vue-router'
import { useAuth } from './stores/auth'

const auth = useAuth()
const router = useRouter()

async function onLogout() {
  await auth.logout()
  router.push('/')
}
</script>

<template>
  <nav class="app-navbar sticky-top">
    <div class="container-xxl px-3 px-lg-4 d-flex align-items-center py-2">
      <RouterLink to="/" class="navbar-brand mb-0 me-4 fs-4 text-decoration-none">
        <span class="brand-gradient">CDT</span>s
      </RouterLink>

      <div class="d-none d-md-flex align-items-center gap-1 me-auto">
        <RouterLink to="/" class="nav-link text-decoration-none">
          <i class="bi bi-graph-up-arrow me-1"></i>Simulador
        </RouterLink>
        <RouterLink v-if="auth.user.value" to="/dashboard" class="nav-link text-decoration-none">
          <i class="bi bi-person-circle me-1"></i>Mi cuenta
        </RouterLink>
      </div>

      <div class="d-flex align-items-center gap-2 ms-auto">
        <template v-if="auth.user.value">
          <span class="avatar me-1">{{ auth.user.value.name[0]?.toUpperCase() }}</span>
          <span class="d-none d-sm-inline text-body-secondary me-2 fw-semibold small">
            {{ auth.user.value.name }}
          </span>
          <button class="btn btn-outline-secondary btn-sm" @click="onLogout">
            <i class="bi bi-box-arrow-right me-1"></i>Salir
          </button>
        </template>
        <template v-else>
          <RouterLink to="/login" class="btn btn-outline-primary btn-sm">
            Iniciar sesión
          </RouterLink>
          <RouterLink to="/register" class="btn btn-primary btn-sm">
            Crear cuenta
          </RouterLink>
        </template>
      </div>
    </div>
  </nav>

  <main class="container-xxl px-3 px-lg-4 py-4 flex-grow-1 w-100">
    <RouterView />
  </main>

  <footer class="app-footer">
    <div class="container-xxl px-3 px-lg-4 py-4 d-flex flex-wrap justify-content-between align-items-center gap-3">
      <div class="d-flex align-items-center gap-3">
        <span class="footer-brand fs-5"><span style="color:#a78bfa;">CDT</span>s</span>
        <span class="small d-none d-md-inline">Tu dinero merece crecer mejor.</span>
      </div>
      <div class="small text-end">
        Proyecto académico · Simulaciones referenciales — no constituye asesoría financiera.
      </div>
    </div>
  </footer>
</template>
