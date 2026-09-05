<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { login } from '../api/access'
import { useAuth } from '../stores/auth'

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const auth = useAuth()
const router = useRouter()

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const res = await login({ username: username.value, password: password.value })
    auth.setToken(res.token)
    await auth.loadUser()
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.code === 'invalid_credentials' ? 'Usuario o contraseña incorrectos' : e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="row justify-content-center">
    <div class="col-md-5">
      <div class="card shadow-sm">
        <div class="card-body">
          <h4 class="card-title mb-4">Iniciar sesión</h4>
          <form @submit.prevent="submit">
            <div class="mb-3">
              <label class="form-label">Usuario</label>
              <input v-model="username" class="form-control" required autocomplete="username" />
            </div>
            <div class="mb-3">
              <label class="form-label">Contraseña</label>
              <input v-model="password" type="password" class="form-control" required autocomplete="current-password" />
            </div>
            <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
            <button class="btn btn-primary w-100" :disabled="loading">
              {{ loading ? 'Entrando…' : 'Entrar' }}
            </button>
          </form>
          <p class="mt-3 text-center mb-0">
            ¿No tienes cuenta? <RouterLink to="/register">Regístrate</RouterLink>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
