<script setup lang="ts">
import { RouterView, RouterLink, useRouter } from 'vue-router'
import { useAuth } from './stores/auth'

const auth = useAuth()
const router = useRouter()

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <nav class="navbar navbar-dark bg-dark">
    <div class="container">
      <RouterLink to="/" class="navbar-brand mb-0 h1">CDTs</RouterLink>
      <div v-if="auth.user.value" class="d-flex align-items-center gap-3">
        <span class="text-light">{{ auth.user.value.name }}</span>
        <button class="btn btn-outline-light btn-sm" @click="onLogout">Salir</button>
      </div>
    </div>
  </nav>
  <main class="container py-4">
    <RouterView />
  </main>
</template>
