<script setup lang="ts">
import { useAuth } from '../stores/auth'

const auth = useAuth()
</script>

<template>
  <div v-if="auth.user.value">
    <h1 class="mb-3">Hola, {{ auth.user.value.name }}</h1>
    <p class="text-muted">Bienvenido a CDTs. Aquí veras tus certificados de depósito a término.</p>

    <div class="row g-3 mt-2">
      <div class="col-md-4">
        <div class="card">
          <div class="card-body">
            <h6 class="text-uppercase text-muted small mb-1">Usuario</h6>
            <div class="fs-5">@{{ auth.user.value.username }}</div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card">
          <div class="card-body">
            <h6 class="text-uppercase text-muted small mb-1">ID</h6>
            <div class="fs-5">#{{ auth.user.value.id }}</div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card">
          <div class="card-body">
            <h6 class="text-uppercase text-muted small mb-1">Miembro desde</h6>
            <div class="fs-6">{{ auth.user.value.created_at?.slice(0, 10) || '—' }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="alert alert-info mt-4 mb-0">
      Los CDTs vendrán aquí cuando conectemos el servicio <code>digital_signature</code>.
    </div>
  </div>
  <div v-else class="text-center py-5">
    <div class="spinner-border text-secondary" role="status"></div>
  </div>
</template>
