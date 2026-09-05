<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { register, login } from '../api/access'
import { useAuth } from '../stores/auth'

const username = ref('')
const name = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const auth = useAuth()
const router = useRouter()

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await register({ username: username.value, name: name.value, password: password.value })
    const res = await login({ username: username.value, password: password.value })
    auth.setToken(res.token)
    await auth.loadUser()
    router.push('/dashboard')
  } catch (e: any) {
    error.value = mapError(e.code) || e.message
  } finally {
    loading.value = false
  }
}

function mapError(code: string): string {
  const dict: Record<string, string> = {
    username_taken: 'Ese usuario ya existe',
    password_too_short: 'La contraseña debe tener al menos 8 caracteres',
    missing_fields: 'Completa todos los campos',
  }
  return dict[code] || ''
}
</script>

<template>
  <div class="row justify-content-center">
    <div class="col-md-5">
      <div class="card shadow-sm">
        <div class="card-body">
          <h4 class="card-title mb-4">Crear cuenta</h4>
          <form @submit.prevent="submit">
            <div class="mb-3">
              <label class="form-label">Usuario</label>
              <input v-model="username" class="form-control" required autocomplete="username" />
            </div>
            <div class="mb-3">
              <label class="form-label">Nombre completo</label>
              <input v-model="name" class="form-control" required />
            </div>
            <div class="mb-3">
              <label class="form-label">Contraseña</label>
              <input v-model="password" type="password" class="form-control" required minlength="8" autocomplete="new-password" />
              <div class="form-text">Mínimo 8 caracteres</div>
            </div>
            <div v-if="error" class="alert alert-danger py-2">{{ error }}</div>
            <button class="btn btn-primary w-100" :disabled="loading">
              {{ loading ? 'Creando…' : 'Registrarme' }}
            </button>
          </form>
          <p class="mt-3 text-center mb-0">
            ¿Ya tienes cuenta? <RouterLink to="/login">Inicia sesión</RouterLink>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
