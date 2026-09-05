<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  getLoadRun, listLoadRuns, startLoadRun,
  type LoadRunDetail, type LoadRunSummary,
} from '../../api/tests'

const SCENARIOS = [
  { id: 'lambda', label: 'API básica (solo Lambda)', desc: 'GET /health del servicio de firma' },
  { id: 'db', label: 'API + base de datos', desc: 'Consulta de proceso de firma contra PostgreSQL' },
]
const REQUEST_OPTIONS = [50, 100, 200, 400]
const CONCURRENCY_OPTIONS = [2, 4, 6, 8]

const scenario = ref('lambda')
const requests = ref(100)
const concurrency = ref(4)

const runs = ref<LoadRunSummary[]>([])
const selected = ref<LoadRunDetail | null>(null)
const launching = ref(false)

const STATUS_META: Record<string, { label: string; cls: string; icon: string }> = {
  running: { label: 'Ejecutando', cls: 'qa-badge-running', icon: 'bi-arrow-repeat' },
  passed: { label: 'Exitosa', cls: 'qa-badge-passed', icon: 'bi-check-circle-fill' },
  failed: { label: 'Con errores', cls: 'qa-badge-failed', icon: 'bi-x-circle-fill' },
  error: { label: 'Error', cls: 'qa-badge-failed', icon: 'bi-exclamation-triangle-fill' },
}

function scenarioLabel(id: string | null | undefined): string {
  return SCENARIOS.find((s) => s.id === id)?.label ?? id ?? ''
}

const stats = computed(() => selected.value?.results ?? null)

const progress = computed(() => {
  if (!selected.value) return 0
  if (selected.value.status !== 'running') return 100
  const total = selected.value.config.requests || 1
  return Math.round(((stats.value?.done ?? 0) / total) * 100)
})

const successPct = computed(() => {
  const s = stats.value
  if (!s?.done) return null
  return Math.round(((s.ok ?? 0) / s.done) * 100)
})

// Grafica: una barra por peticion, en orden de llegada, escalada a la latencia maxima
const chart = computed(() => {
  const s = stats.value
  if (!s?.samples?.length) return null
  const total = selected.value?.config.requests || s.samples.length
  const maxMs = Math.max(...s.samples.map((x) => x.ms), 1)
  const barW = 600 / total
  return {
    maxMs,
    barW,
    bars: s.samples.map((x, i) => ({
      x: i * barW,
      h: Math.max(2, (x.ms / maxMs) * 130),
      ok: x.ok,
    })),
  }
})

function hora(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : ''
}

function ms(v: number | null | undefined): string {
  if (v == null) return '—'
  return v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`
}

let poll: number | undefined

async function refreshList() {
  try {
    runs.value = await listLoadRuns()
  } catch { /* siguiente tick */ }
}

async function select(id: number) {
  try {
    selected.value = await getLoadRun(id)
  } catch { /* ignora */ }
}

async function tick() {
  if (!selected.value || selected.value.status !== 'running') return
  try {
    selected.value = await getLoadRun(selected.value.id)
    if (selected.value.status !== 'running') refreshList()
  } catch { /* siguiente tick */ }
}

async function launch() {
  if (launching.value) return
  launching.value = true
  try {
    const r = await startLoadRun({
      scenario: scenario.value,
      requests: requests.value,
      concurrency: concurrency.value,
    })
    await refreshList()
    await select(r.id)
  } finally {
    launching.value = false
  }
}

onMounted(async () => {
  await refreshList()
  if (runs.value.length) await select(runs.value[0].id)
  poll = window.setInterval(tick, 2000)
})
onUnmounted(() => window.clearInterval(poll))
</script>

<template>
  <p class="qa-muted small mb-4">
    Dispara ráfagas de peticiones concurrentes desde una Lambda contra los servicios desplegados
    y mide latencias reales (promedio, percentiles, throughput) en vivo.
  </p>

  <div class="row g-4">
    <!-- Configuracion + historial -->
    <div class="col-lg-4">
      <div class="qa-card p-4 mb-4">
        <h6 class="qa-title mb-3">Nueva prueba</h6>

        <label class="form-label small qa-muted mb-1">Escenario</label>
        <select v-model="scenario" class="form-select qa-select mb-1">
          <option v-for="s in SCENARIOS" :key="s.id" :value="s.id">{{ s.label }}</option>
        </select>
        <div class="qa-muted mb-3" style="font-size: 0.72rem;">
          {{ SCENARIOS.find((s) => s.id === scenario)?.desc }}
        </div>

        <div class="row g-3 mb-4">
          <div class="col-6">
            <label class="form-label small qa-muted mb-1">Peticiones</label>
            <select v-model.number="requests" class="form-select qa-select">
              <option v-for="n in REQUEST_OPTIONS" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <div class="col-6">
            <label class="form-label small qa-muted mb-1">Concurrencia</label>
            <select v-model.number="concurrency" class="form-select qa-select">
              <option v-for="n in CONCURRENCY_OPTIONS" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
        </div>

        <button
          class="btn btn-qa w-100"
          :disabled="launching || selected?.status === 'running'"
          @click="launch"
        >
          <span v-if="launching || selected?.status === 'running'" class="spinner-border spinner-border-sm me-2"></span>
          <i v-else class="bi bi-lightning-charge-fill me-1"></i>
          {{ selected?.status === 'running' ? 'Ejecutando…' : 'Lanzar carga' }}
        </button>
        <div class="qa-muted mt-2" style="font-size: 0.7rem;">
          <i class="bi bi-info-circle me-1"></i>La cuenta permite 10 Lambdas concurrentes;
          con más de 8 hilos aparece throttling.
        </div>
      </div>

      <div class="qa-card p-3">
        <h6 class="qa-title px-2 pt-1 mb-2">Corridas</h6>
        <p v-if="!runs.length" class="qa-muted small px-2 mb-2">
          Aún no hay pruebas de carga. Lanza la primera.
        </p>
        <button
          v-for="r in runs"
          :key="r.id"
          class="qa-run-item"
          :class="{ active: selected?.id === r.id }"
          @click="select(r.id)"
        >
          <span class="qa-badge" :class="STATUS_META[r.status].cls">
            <i class="bi me-1" :class="STATUS_META[r.status].icon"></i>{{ STATUS_META[r.status].label }}
          </span>
          <span class="small fw-semibold qa-mono">#{{ r.id }}</span>
          <span class="small qa-muted ms-auto text-end">
            {{ r.requests }}req ×{{ r.concurrency }} · {{ hora(r.started_at) }}
          </span>
        </button>
      </div>
    </div>

    <!-- Detalle -->
    <div class="col-lg-8">
      <div v-if="!selected" class="qa-card p-5 text-center qa-muted">
        Configura y lanza una prueba de carga.
      </div>

      <template v-else>
        <div class="qa-card p-4 mb-3">
          <div class="d-flex flex-wrap align-items-center gap-3 mb-3">
            <span class="qa-badge fs-6" :class="STATUS_META[selected.status].cls">
              <i class="bi me-1" :class="STATUS_META[selected.status].icon"></i>
              {{ STATUS_META[selected.status].label }}
            </span>
            <span class="fw-bold qa-mono">carga #{{ selected.id }}</span>
            <span class="qa-muted small">
              {{ scenarioLabel(selected.config.scenario) }} ·
              {{ selected.config.requests }} peticiones · {{ selected.config.concurrency }} hilos
            </span>
            <span class="qa-muted small ms-auto">
              {{ hora(selected.started_at) }}{{ selected.finished_at ? ` — ${hora(selected.finished_at)}` : '' }}
            </span>
          </div>
          <div class="qa-progress mb-2">
            <div
              class="qa-progress-bar"
              :class="{ running: selected.status === 'running', failed: (stats?.ko ?? 0) > 0 }"
              :style="{ width: `${progress}%` }"
            ></div>
          </div>
          <div class="small qa-muted">
            <span class="qa-pass fw-semibold">{{ stats?.ok ?? 0 }} exitosas</span>
            <span v-if="stats?.ko" class="qa-fail fw-semibold"> · {{ stats.ko }} con error</span>
            · {{ stats?.done ?? 0 }}/{{ selected.config.requests }} completadas
            <span v-if="stats?.elapsed"> · {{ stats.elapsed }}s</span>
          </div>
        </div>

        <div class="row g-3 mb-3">
          <div class="col-6 col-md-4 col-xl-2" v-for="t in [
            { label: 'p50', value: ms(stats?.p50) },
            { label: 'p90', value: ms(stats?.p90) },
            { label: 'p95', value: ms(stats?.p95) },
            { label: 'promedio', value: ms(stats?.avg) },
            { label: 'máxima', value: ms(stats?.max) },
            { label: 'throughput', value: stats?.rps != null ? `${stats.rps} req/s` : '—' },
          ]" :key="t.label">
            <div class="qa-stat">
              <div class="qa-stat-value qa-mono">{{ t.value }}</div>
              <div class="qa-stat-label">{{ t.label }}</div>
            </div>
          </div>
        </div>

        <div class="qa-card p-4">
          <div class="d-flex align-items-center mb-2">
            <h6 class="qa-title mb-0">Latencia por petición</h6>
            <span class="qa-muted small ms-auto qa-mono" v-if="chart">máx {{ ms(chart.maxMs) }}</span>
          </div>
          <div v-if="!chart" class="qa-muted small py-4 text-center">
            Esperando las primeras respuestas…
          </div>
          <svg v-else class="qa-chart" viewBox="0 0 600 140" preserveAspectRatio="none">
            <rect
              v-for="(b, i) in chart.bars"
              :key="i"
              :x="b.x"
              :y="140 - b.h"
              :width="Math.max(chart.barW * 0.85, 0.5)"
              :height="b.h"
              :fill="b.ok ? '#10b981' : '#ef4444'"
              opacity="0.9"
            />
          </svg>
          <div class="d-flex gap-3 mt-2 small qa-muted">
            <span><span class="qa-legend" style="background:#10b981;"></span>respuesta esperada</span>
            <span><span class="qa-legend" style="background:#ef4444;"></span>error o timeout</span>
            <span v-if="successPct != null" class="ms-auto qa-mono">éxito: {{ successPct }}%</span>
          </div>
        </div>

        <div v-if="selected.status === 'running'" class="text-center qa-muted small py-3">
          <span class="spinner-border spinner-border-sm me-2"></span>
          Generando carga desde la nube, las métricas se actualizan en vivo…
        </div>
      </template>
    </div>
  </div>
</template>
