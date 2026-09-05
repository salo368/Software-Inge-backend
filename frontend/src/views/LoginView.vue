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
  <div class="auth-bg">
    <div class="auth-card">
      <div class="text-center mb-4">
        <div class="fs-3 fw-bolder">
          <span class="brand-gradient">CDT</span>s
        </div>
        <p class="text-body-secondary mb-0">Bienvenido de vuelta</p>
      </div>

      <div class="card shadow-sm">
        <div class="card-body p-4 p-lg-5">
          <h5 class="fw-bold mb-4">Iniciar sesión</h5>
          <form @submit.prevent="submit">
            <div class="mb-3">
              <label class="form-label small fw-semibold text-body-secondary">USUARIO</label>
              <input v-model="username" class="form-control form-control-lg" required autocomplete="username" />
            </div>
            <div class="mb-4">
              <label class="form-label small fw-semibold text-body-secondary">CONTRASEÑA</label>
              <input v-model="password" type="password" class="form-control form-control-lg" required autocomplete="current-password" />
            </div>
            <div v-if="error" class="alert alert-danger py-2 small">
              <i class="bi bi-exclamation-triangle me-1"></i>{{ error }}
            </div>
            <button class="btn btn-primary btn-lg w-100" :disabled="loading">
              <span v-if="loading" class="spinner-border spinner-border-sm me-2"></span>
              {{ loading ? 'Entrando…' : 'Entrar' }}
            </button>
          </form>
        </div>
      </div>

      <p class="mt-4 text-center text-body-secondary">
        ¿No tienes cuenta?
        <RouterLink to="/register" class="fw-semibold text-decoration-none" style="color: var(--brand-dark);">
          Regístrate gratis
        </RouterLink>
      </p>
    </div>
  </div>
</template>
