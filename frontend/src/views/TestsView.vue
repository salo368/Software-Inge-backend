<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  getTestRun, listTestRuns, startTestRun,
  type TestResult, type TestRunDetail, type TestRunSummary,
} from '../api/tests'

const TOTAL_ESPERADO = 26

const runs = ref<TestRunSummary[]>([])
const selected = ref<TestRunDetail | null>(null)
const launching = ref(false)
const expanded = ref('')

const FILE_LABELS: Record<string, string> = {
  'test_01_unitarias_validacion.py': 'Unitarias — validación OCR',
  'test_02_creacion_proceso.py': 'E2E — creación del proceso',
  'test_03_validacion_fotos.py': 'E2E — validación de fotos (Rekognition)',
  'test_04_otp_y_firma.py': 'E2E — OTP, certificado y firma',
}

const STATUS_META: Record<string, { label: string; cls: string; icon: string }> = {
  running: { label: 'Ejecutando', cls: 'text-bg-warning', icon: 'bi-arrow-repeat' },
  passed: { label: 'Exitosa', cls: 'text-bg-success', icon: 'bi-check-circle-fill' },
  failed: { label: 'Con fallos', cls: 'text-bg-danger', icon: 'bi-x-circle-fill' },
  error: { label: 'Error', cls: 'text-bg-danger', icon: 'bi-exclamation-triangle-fill' },
}

const grouped = computed(() => {
  if (!selected.value) return []
  const groups: { file: string; label: string; results: TestResult[] }[] = []
  for (const r of selected.value.results) {
    let g = groups.find((x) => x.file === r.file)
    if (!g) {
      g = { file: r.file, label: FILE_LABELS[r.file] ?? r.file, results: [] }
      groups.push(g)
    }
    g.results.push(r)
  }
  return groups
})

const progress = computed(() => {
  if (!selected.value) return 0
  if (selected.value.status !== 'running') return 100
  return Math.min(96, Math.round((selected.value.results.length / TOTAL_ESPERADO) * 100))
})

const passedCount = computed(() => selected.value?.results.filter((r) => r.outcome === 'passed').length ?? 0)
const failedCount = computed(() => selected.value?.results.filter((r) => r.outcome === 'failed').length ?? 0)

function hora(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : ''
}

let poll: number | undefined

async function refreshList() {
  try {
    runs.value = await listTestRuns()
  } catch { /* siguiente tick */ }
}

async function select(id: number) {
  expanded.value = ''
  try {
    selected.value = await getTestRun(id)
  } catch { /* ignora */ }
}

async function tick() {
  if (!selected.value || selected.value.status !== 'running') return
  try {
    selected.value = await getTestRun(selected.value.id)
    if (selected.value.status !== 'running') refreshList()
  } catch { /* siguiente tick */ }
}

async function launch() {
  if (launching.value) return
  launching.value = true
  try {
    const r = await startTestRun()
    await refreshList()
    await select(r.id)
  } finally {
    launching.value = false
  }
}

onMounted(async () => {
  await refreshList()
  if (runs.value.length) await select(runs.value[0].id)
  poll = window.setInterval(tick, 2500)
})
onUnmounted(() => window.clearInterval(poll))
</script>

<template>
  <div>
    <div class="d-flex flex-wrap justify-content-between align-items-center mb-4 gap-3">
      <div>
        <h3 class="fw-bolder mb-1">Panel de pruebas · Firma digital</h3>
        <p class="text-body-secondary mb-0">
          Suite TDD ejecutada en la nube contra los servicios reales. Cada corrida envía correos y usa OCR real.
        </p>
      </div>
      <button class="btn btn-primary px-4" :disabled="launching || selected?.status === 'running'" @click="launch">
        <span v-if="launching || selected?.status === 'running'" class="spinner-border spinner-border-sm me-2"></span>
        <i v-else class="bi bi-play-fill me-1"></i>
        {{ selected?.status === 'running' ? 'Ejecutando…' : 'Ejecutar pruebas' }}
      </button>
    </div>

    <div class="row g-4">
      <!-- Historial -->
      <div class="col-lg-4">
        <div class="card shadow-sm">
          <div class="card-body p-3">
            <h6 class="fw-bold px-2 pt-1 mb-2">Corridas</h6>
            <p v-if="!runs.length" class="text-body-secondary small px-2 mb-2">
              Aún no hay corridas. Lanza la primera.
            </p>
            <button
              v-for="r in runs"
              :key="r.id"
              class="run-item"
              :class="{ active: selected?.id === r.id }"
              @click="select(r.id)"
            >
              <span class="badge" :class="STATUS_META[r.status].cls">
                <i class="bi me-1" :class="STATUS_META[r.status].icon"></i>{{ STATUS_META[r.status].label }}
              </span>
              <span class="small fw-semibold">Corrida #{{ r.id }}</span>
              <span class="small text-body-secondary ms-auto">
                {{ r.status === 'running' ? `${r.total} de ${TOTAL_ESPERADO}` : `${r.passed}/${r.total}` }}
                · {{ hora(r.started_at) }}
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- Detalle -->
      <div class="col-lg-8">
        <div v-if="!selected" class="card shadow-sm">
          <div class="card-body p-5 text-center text-body-secondary">
            Selecciona una corrida o lanza una nueva.
          </div>
        </div>

        <template v-else>
          <div class="card shadow-sm mb-3">
            <div class="card-body p-4">
              <div class="d-flex flex-wrap align-items-center gap-3 mb-2">
                <span class="badge fs-6" :class="STATUS_META[selected.status].cls">
                  <i class="bi me-1" :class="STATUS_META[selected.status].icon"></i>
                  {{ STATUS_META[selected.status].label }}
                </span>
                <span class="fw-bold">Corrida #{{ selected.id }}</span>
                <span class="text-body-secondary small ms-auto">
                  {{ hora(selected.started_at) }}{{ selected.finished_at ? ` — ${hora(selected.finished_at)}` : '' }}
                </span>
              </div>
              <div class="progress mb-2" style="height: 10px;">
                <div
                  class="progress-bar"
                  :class="selected.status === 'running' ? 'progress-bar-striped progress-bar-animated' : failedCount ? 'bg-danger' : 'bg-success'"
                  :style="{ width: `${progress}%` }"
                ></div>
              </div>
              <div class="small text-body-secondary">
                <span class="money-positive fw-semibold">{{ passedCount }} exitosas</span>
                <span v-if="failedCount" class="text-danger fw-semibold"> · {{ failedCount }} fallidas</span>
                · {{ selected.results.length }} ejecutadas
              </div>
            </div>
          </div>

          <div v-for="g in grouped" :key="g.file" class="card shadow-sm mb-3">
            <div class="card-body p-4">
              <h6 class="fw-bold mb-3">{{ g.label }}</h6>
              <div v-for="r in g.results" :key="r.name" class="test-row" @click="expanded = expanded === r.name ? '' : r.name">
                <i
                  class="bi"
                  :class="r.outcome === 'passed' ? 'bi-check-circle-fill text-success' : 'bi-x-circle-fill text-danger'"
                ></i>
                <div class="flex-grow-1">
                  <div class="small fw-semibold">{{ r.escenario || r.name }}</div>
                  <div class="text-body-secondary" style="font-size: 0.75rem;">{{ r.name }}</div>
                  <pre v-if="expanded === r.name && r.error" class="test-error">{{ r.error }}</pre>
                </div>
                <span class="small text-body-secondary text-nowrap">{{ r.duration.toFixed(2) }}s</span>
              </div>
            </div>
          </div>

          <div v-if="selected.status === 'running'" class="text-center text-body-secondary small py-2">
            <span class="spinner-border spinner-border-sm me-2"></span>Ejecutando en la nube, los resultados aparecen en vivo…
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
