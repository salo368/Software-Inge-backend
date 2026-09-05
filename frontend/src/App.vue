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
    <div class="container-fluid px-4 d-flex align-items-center py-2">
      <RouterLink to="/" class="navbar-brand mb-0 me-4 fs-4">
        <span class="text-primary">CDT</span>s
      </RouterLink>

      <div class="d-none d-md-flex align-items-center gap-1 me-auto">
        <RouterLink to="/" class="nav-link">Simulador</RouterLink>
        <RouterLink v-if="auth.user.value" to="/dashboard" class="nav-link">Mi cuenta</RouterLink>
      </div>

      <div class="d-flex align-items-center gap-2 ms-auto">
        <template v-if="auth.user.value">
          <span class="avatar me-2">{{ auth.user.value.name[0]?.toUpperCase() }}</span>
          <span class="d-none d-sm-inline text-body-secondary me-2 fw-medium">
            {{ auth.user.value.name }}
          </span>
          <button class="btn btn-outline-secondary btn-sm" @click="onLogout">
            Salir
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

  <main class="container-fluid px-4 py-4">
    <RouterView />
  </main>
</template>
