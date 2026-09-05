<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useAuth } from '../stores/auth'
import { listCdts, type Cdt } from '../api/cdts'
import { bankById } from '../data/banks'
import { STAGES, stageIndex } from '../data/stages'
import { formatCOP } from '../utils/format'

const auth = useAuth()
const cdts = ref<Cdt[]>([])
const loading = ref(true)

const activeCount = computed(() => cdts.value.filter((c) => c.stage !== 'terminado').length)

function stageLabel(c: Cdt): string {
  return STAGES[stageIndex(c.stage)]?.label ?? c.stage
}

function progressPct(c: Cdt): number {
  return (stageIndex(c.stage) / (STAGES.length - 1)) * 100
}

onMounted(async () => {
  try {
    cdts.value = await listCdts()
  } catch {
    cdts.value = []
  } finally {
    loading.value = false
  }
})
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
                <div class="text-body-secondary small text-uppercase fw-semibold">CDTs en proceso</div>
                <div class="fs-5 fw-bold">{{ activeCount }}</div>
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

    <!-- Lista de CDTs -->
    <div v-if="loading" class="text-center py-5">
      <div class="spinner-border text-primary" role="status"></div>
    </div>

    <div v-else-if="cdts.length === 0" class="card shadow-sm">
      <div class="card-body p-5 text-center">
        <div class="empty-state-icon mb-3">
          <i class="bi bi-file-earmark-text"></i>
        </div>
        <h5 class="fw-bold mb-2">Aún no tienes CDTs</h5>
        <p class="text-body-secondary mb-4" style="max-width: 28rem; margin-inline: auto;">
          Simula tu inversión, elige la entidad que más te convenga y abre
          tu primer CDT en minutos. Aquí verás su progreso siempre.
        </p>
        <RouterLink to="/" class="btn btn-outline-primary">
          Simular mi primer CDT
        </RouterLink>
      </div>
    </div>

    <template v-else>
      <h5 class="fw-bold mb-3">Mis CDTs</h5>
      <div v-for="c in cdts" :key="c.id" class="card shadow-sm mb-3">
        <div class="card-body p-4">
          <div class="row g-3 align-items-center">
            <div class="col-md-3">
              <div class="d-flex align-items-center gap-2">
                <div v-if="bankById(c.bank)" class="bank-logo bank-logo-sm">
                  <img :src="bankById(c.bank)!.logo" :alt="bankById(c.bank)!.name" loading="lazy" />
                </div>
                <div>
                  <div class="fw-bold lh-sm">{{ bankById(c.bank)?.name ?? 'CDT' }}</div>
                  <div class="small text-body-secondary">Abierto el {{ c.opened_at?.slice(0, 10) }}</div>
                </div>
              </div>
            </div>
            <div class="col-md-3">
              <div class="fw-bold">{{ formatCOP(Number(c.amount)) }}</div>
              <div class="small text-body-secondary">{{ c.term }} días · {{ Number(c.rate).toFixed(2) }}% E.A.</div>
            </div>
            <div class="col-md-4">
              <div class="d-flex justify-content-between small mb-1">
                <span class="fw-semibold" :class="c.stage === 'terminado' ? 'money-positive' : ''">
                  <i class="bi me-1" :class="c.stage === 'terminado' ? 'bi-check-circle-fill' : 'bi-clock-history'"></i>
                  {{ c.stage === 'terminado' ? 'Terminado' : `En ${stageLabel(c).toLowerCase()}` }}
                </span>
                <span class="text-body-secondary">{{ Math.round(progressPct(c)) }}%</span>
              </div>
              <div class="progress" style="height: 8px;">
                <div
                  class="progress-bar"
                  :class="c.stage === 'terminado' ? 'bg-success' : ''"
                  :style="{ width: `${progressPct(c)}%` }"
                ></div>
              </div>
            </div>
            <div class="col-md-2 text-md-end">
              <RouterLink
                :to="`/cdt/${c.id}`"
                class="btn"
                :class="c.stage === 'terminado' ? 'btn-outline-secondary' : 'btn-primary'"
              >
                {{ c.stage === 'terminado' ? 'Ver' : 'Retomar' }}
                <i class="bi bi-arrow-right ms-1"></i>
              </RouterLink>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
  <div v-else class="text-center py-5">
    <div class="spinner-border text-primary" role="status"></div>
  </div>
</template>
