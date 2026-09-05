<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useAuth } from '../stores/auth'

const auth = useAuth()
</script>

<template>
  <div v-if="auth.user.value">
    <div class="d-flex flex-wrap justify-content-between align-items-center mb-4 gap-3">
      <div>
        <h2 class="fw-bolder mb-1">Hola, {{ auth.user.value.name }} 👋</h2>
        <p class="text-body-secondary mb-0">Este es tu espacio personal en CDTs.</p>
      </div>
      <RouterLink to="/" class="btn btn-primary">
        <i class="bi bi-graph-up-arrow me-2"></i>Ir al simulador
      </RouterLink>
    </div>

    <div class="row g-3 mb-4">
      <div class="col-md-4">
        <div class="card shadow-sm h-100">
          <div class="card-body p-4">
            <div class="d-flex align-items-center gap-3">
              <div class="empty-state-icon" style="width: 52px; height: 52px; font-size: 1.3rem; border-radius: 1rem;">
                <i class="bi bi-person-fill"></i>
              </div>
              <div>
                <div class="text-body-secondary small text-uppercase fw-semibold">Usuario</div>
                <div class="fs-5 fw-bold">@{{ auth.user.value.username }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card shadow-sm h-100">
          <div class="card-body p-4">
            <div class="d-flex align-items-center gap-3">
              <div class="empty-state-icon" style="width: 52px; height: 52px; font-size: 1.3rem; border-radius: 1rem;">
                <i class="bi bi-wallet2"></i>
              </div>
              <div>
                <div class="text-body-secondary small text-uppercase fw-semibold">CDTs activos</div>
                <div class="fs-5 fw-bold">0</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="card shadow-sm h-100">
          <div class="card-body p-4">
            <div class="d-flex align-items-center gap-3">
              <div class="empty-state-icon" style="width: 52px; height: 52px; font-size: 1.3rem; border-radius: 1rem;">
                <i class="bi bi-calendar-check"></i>
              </div>
              <div>
                <div class="text-body-secondary small text-uppercase fw-semibold">Miembro desde</div>
                <div class="fs-6 fw-bold">{{ auth.user.value.created_at?.slice(0, 10) || '—' }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card shadow-sm">
      <div class="card-body p-5 text-center">
        <div class="empty-state-icon mb-3">
          <i class="bi bi-file-earmark-text"></i>
        </div>
        <h5 class="fw-bold mb-2">Aún no tienes CDTs</h5>
        <p class="text-body-secondary mb-4" style="max-width: 28rem; margin-inline: auto;">
          Cuando abras tu primer CDT con nosotros, aquí verás su progreso,
          fechas de vencimiento y rendimientos en tiempo real.
        </p>
        <RouterLink to="/" class="btn btn-outline-primary">
          Simular mi primer CDT
        </RouterLink>
      </div>
    </div>
  </div>
  <div v-else class="text-center py-5">
    <div class="spinner-border text-primary" role="status"></div>
  </div>
</template>
