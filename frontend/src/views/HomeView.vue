<script setup lang="ts">
import { computed, ref } from 'vue'
import { BANKS, type Bank } from '../data/banks'
import { calcCdt, formatCOP } from '../utils/format'

const amount = ref<number>(5_000_000)
const termYears = ref<number>(1)

interface Row extends Bank {
  interest: number
  final: number
}

const results = computed<Row[]>(() =>
  BANKS
    .map((b) => ({ ...b, ...calcCdt(amount.value || 0, b.rate, termYears.value) }))
    .sort((a, b) => b.final - a.final),
)

const best = computed(() => results.value[0])
const worst = computed(() => results.value[results.value.length - 1])
const diff = computed(() => (best.value && worst.value ? best.value.interest - worst.value.interest : 0))
</script>

<template>
  <div class="container-xxl px-0">
    <!-- Hero -->
    <section class="hero rounded-4 p-4 p-lg-5 mb-4">
      <div class="row align-items-center g-4">
        <div class="col-lg-7">
          <span class="badge bg-white text-primary border border-primary-subtle mb-3">
            Simulador de CDT
          </span>
          <h1 class="display-5 mb-3">
            Compara cuánto <span class="text-primary">ganarías</span> con tu CDT
          </h1>
          <p class="lead text-body-secondary mb-0">
            Ingresa el monto que quieres invertir y descubre cuál entidad financiera
            te ofrece la mejor rentabilidad en Colombia.
          </p>
        </div>
        <div class="col-lg-5">
          <div v-if="best" class="card border-0 shadow-sm">
            <div class="card-body p-4">
              <div class="d-flex align-items-center gap-3 mb-3">
                <div class="fs-2">🏆</div>
                <div>
                  <div class="text-body-secondary small text-uppercase fw-semibold">
                    Mejor opción
                  </div>
                  <div class="fs-5 fw-bold">{{ best.name }}</div>
                </div>
              </div>
              <div class="row g-3">
                <div class="col-6">
                  <div class="text-body-secondary small">Tasa E.A.</div>
                  <div class="fs-4 fw-bold text-primary">{{ best.rate.toFixed(2) }}%</div>
                </div>
                <div class="col-6">
                  <div class="text-body-secondary small">Ganarías</div>
                  <div class="fs-4 fw-bold text-success">
                    +{{ formatCOP(best.interest) }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Controles -->
    <div class="card shadow-sm mb-4">
      <div class="card-body p-4">
        <div class="row g-3 align-items-end">
          <div class="col-md-8">
            <label class="form-label small text-uppercase text-body-secondary fw-semibold">
              Monto a invertir
            </label>
            <div class="input-group input-group-lg">
              <span class="input-group-text">$</span>
              <input
                v-model.number="amount"
                type="number"
                class="form-control"
                min="0"
                step="100000"
                placeholder="5.000.000"
              />
              <span class="input-group-text">COP</span>
            </div>
            <div class="form-text">= {{ formatCOP(amount || 0) }}</div>
          </div>
          <div class="col-md-4">
            <label class="form-label small text-uppercase text-body-secondary fw-semibold">
              Plazo
            </label>
            <select v-model.number="termYears" class="form-select form-select-lg" disabled>
              <option :value="1">1 año</option>
            </select>
            <div class="form-text">Otros plazos próximamente</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Metrica: diferencia entre mejor y peor -->
    <div v-if="diff > 0" class="alert border-0 bg-primary-subtle text-primary-emphasis rounded-4 d-flex align-items-center gap-3 mb-4">
      <span class="fs-4">💡</span>
      <div>
        Escoger la mejor opción vs. la peor te deja
        <strong class="fw-bold">{{ formatCOP(diff) }}</strong> extra al año.
      </div>
    </div>

    <!-- Tabla de resultados -->
    <div class="card shadow-sm">
      <div class="card-body p-0">
        <div class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead>
              <tr>
                <th class="ps-4" style="width: 40%;">Entidad</th>
                <th class="text-center">Tasa E.A.</th>
                <th class="text-end">Interés a 1 año</th>
                <th class="text-end pe-4">Monto final</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, idx) in results" :key="row.id">
                <td class="ps-4">
                  <div class="d-flex align-items-center gap-3">
                    <div
                      class="avatar"
                      :style="{ backgroundColor: row.color }"
                    >
                      {{ row.name[0] }}
                    </div>
                    <div>
                      <div class="fw-semibold">{{ row.name }}</div>
                      <div v-if="idx === 0" class="small text-success fw-medium">
                        Mejor rentabilidad
                      </div>
                    </div>
                  </div>
                </td>
                <td class="text-center">
                  <span class="badge bg-primary-subtle text-primary-emphasis fs-6">
                    {{ row.rate.toFixed(2) }}%
                  </span>
                </td>
                <td class="text-end text-success fw-semibold">
                  +{{ formatCOP(row.interest) }}
                </td>
                <td class="text-end pe-4 fw-bold">
                  {{ formatCOP(row.final) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <p class="text-body-secondary small mt-3 mb-5">
      * Simulación referencial. Las tasas mostradas son ejemplos y no representan ofertas
      vigentes de las entidades. Los cálculos son antes de retención en la fuente.
    </p>
  </div>
</template>
