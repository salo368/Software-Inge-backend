<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BANKS, TERMS, TIER_COLORS, type Bank, type TermKey, type Tier } from '../data/banks'
import { calcCdtDays, formatCOP } from '../utils/format'

// --- Estado del simulador ---
const amount = ref<number>(5_000_000)
const term = ref<TermKey>('360')
const sortBy = ref<'yield' | 'safety'>('yield')

// Anticipacion: los resultados aparecen tras clic explicito.
// Una vez visibles, siguen actualizando en vivo si el usuario cambia inputs.
const showResults = ref(false)

const TIER_RANK: Record<Tier, number> = { 'AAA': 5, 'AA+': 4, 'AA': 3, 'A+': 2, 'A': 1 }

interface Row extends Bank {
  rate: number
  interest: number
  final: number
}

const results = computed<Row[]>(() => {
  const days = TERMS.find((t) => t.key === term.value)!.days
  const rows: Row[] = BANKS.map((b) => {
    const rate = b.rates[term.value]
    const { interest, final } = calcCdtDays(amount.value || 0, rate, days)
    return { ...b, rate, interest, final }
  })

  if (sortBy.value === 'safety') {
    rows.sort((a, b) => TIER_RANK[b.tier] - TIER_RANK[a.tier] || b.rate - a.rate)
  } else {
    rows.sort((a, b) => b.rate - a.rate)
  }
  return rows
})

const isValid = computed(() => (amount.value || 0) > 0 && !!term.value)
const selectedTermLabel = computed(() => TERMS.find((t) => t.key === term.value)?.label ?? '')

function onSimulate() {
  if (!isValid.value) return
  // Fuerza un pequeno "reset" de la reveal para re-disparar la animacion
  showResults.value = false
  requestAnimationFrame(() => { showResults.value = true })
}

// Si el usuario cambia el plazo despues del primer clic, re-anima suavemente
watch(term, () => {
  if (!showResults.value) return
  showResults.value = false
  requestAnimationFrame(() => { showResults.value = true })
})
</script>

<template>
  <div class="container-xxl px-0">

    <!-- Hero -->
    <section class="hero rounded-4 p-4 p-lg-5 mb-4">
      <div class="row g-4 align-items-center">
        <div class="col-lg-8">
          <span class="badge bg-white text-primary border border-primary-subtle mb-3">
            Simulador de CDT
          </span>
          <h1 class="display-5 mb-3">
            Descubre <span class="text-primary">dónde crece más</span> tu dinero
          </h1>
          <p class="lead text-body-secondary mb-0">
            Ingresa tu monto, elige el plazo y compara — no todas las entidades ganan
            lo mismo en todos los plazos, y no todo se trata de la tasa: la solidez
            del banco también cuenta.
          </p>
        </div>
      </div>
    </section>

    <!-- Controles -->
    <div class="card shadow-sm mb-4">
      <div class="card-body p-4">
        <div class="row g-4">
          <div class="col-lg-5">
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

          <div class="col-lg-7">
            <label class="form-label small text-uppercase text-body-secondary fw-semibold">
              Plazo
            </label>
            <div class="d-flex flex-wrap gap-2">
              <button
                v-for="t in TERMS"
                :key="t.key"
                type="button"
                class="btn"
                :class="term === t.key ? 'btn-primary' : 'btn-outline-secondary'"
                @click="term = t.key"
              >
                {{ t.label }}
              </button>
            </div>
            <div class="form-text">Cada entidad ofrece tasas distintas según el plazo.</div>
          </div>
        </div>

        <div class="d-flex justify-content-center mt-4">
          <button
            class="btn btn-primary btn-lg px-5 py-3 shadow-sm"
            :disabled="!isValid"
            @click="onSimulate"
          >
            {{ showResults ? 'Simular de nuevo' : 'Ver mis opciones →' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="!showResults"
      class="text-center py-5 text-body-secondary"
    >
      <div class="fs-1 mb-2">📊</div>
      <h5 class="fw-semibold text-body">Listo cuando quieras</h5>
      <p class="mb-0">Haz click en <em>Ver mis opciones</em> y te mostramos todas las entidades disponibles.</p>
    </div>

    <!-- Resultados -->
    <template v-else>
      <!-- Header de resultados -->
      <div class="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-2">
        <div>
          <h5 class="mb-0">{{ BANKS.length }} entidades disponibles</h5>
          <div class="text-body-secondary small">
            Simulando {{ formatCOP(amount || 0) }} a {{ selectedTermLabel }}
          </div>
        </div>
        <div class="d-flex align-items-center gap-2">
          <label class="text-body-secondary small mb-0">Ordenar por:</label>
          <select v-model="sortBy" class="form-select form-select-sm" style="width: auto;">
            <option value="yield">Mayor rentabilidad</option>
            <option value="safety">Mayor solidez</option>
          </select>
        </div>
      </div>

      <!-- Grid de cards -->
      <div class="row g-3">
        <div
          v-for="(row, idx) in results"
          :key="row.id"
          class="col-12 col-md-6 col-xl-4"
        >
          <div
            class="card h-100 shadow-sm bank-card"
            :style="{ animationDelay: `${idx * 60}ms` }"
          >
            <div class="card-body p-4 d-flex flex-column">
              <!-- Header: avatar + nombre + tier -->
              <div class="d-flex align-items-start gap-3 mb-3">
                <div class="avatar avatar-lg" :style="{ backgroundColor: row.color }">
                  {{ row.name[0] }}
                </div>
                <div class="flex-grow-1">
                  <div class="fw-bold fs-6">{{ row.name }}</div>
                  <div
                    class="tier-badge mt-1"
                    :style="{
                      background: TIER_COLORS[row.tier].bg,
                      color: TIER_COLORS[row.tier].fg,
                    }"
                    :title="`${TIER_COLORS[row.tier].label} — según ${row.ratingBy}`"
                  >
                    {{ row.tier }} · {{ TIER_COLORS[row.tier].label }}
                  </div>
                </div>
              </div>

              <!-- Highlights -->
              <ul class="list-unstyled small text-body-secondary mb-3 flex-grow-1">
                <li v-for="h in row.highlights" :key="h" class="mb-1">
                  <span class="text-primary me-1">•</span>{{ h }}
                </li>
              </ul>

              <!-- Tasa -->
              <div class="d-flex align-items-baseline justify-content-between border-top pt-3">
                <div>
                  <div class="text-body-secondary small">Tasa E.A.</div>
                  <div class="fs-3 fw-bold">{{ row.rate.toFixed(2) }}<span class="fs-6">%</span></div>
                </div>
                <div class="text-end">
                  <div class="text-body-secondary small">Ganarías</div>
                  <div class="fs-5 fw-bold text-success">+{{ formatCOP(row.interest) }}</div>
                </div>
              </div>

              <!-- Monto final + condiciones -->
              <div class="mt-3 pt-3 border-top small">
                <div class="d-flex justify-content-between mb-1">
                  <span class="text-body-secondary">Monto final</span>
                  <span class="fw-semibold">{{ formatCOP(row.final) }}</span>
                </div>
                <div class="d-flex justify-content-between">
                  <span class="text-body-secondary">Monto mínimo</span>
                  <span>{{ formatCOP(row.minAmount) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <p class="text-body-secondary small mt-4 mb-5">
        * Simulación referencial. Las tasas y calificaciones mostradas son ejemplos.
        Consulta con cada entidad las condiciones vigentes y ten en cuenta la retención
        en la fuente (4% sobre intereses) al recibir el pago.
      </p>
    </template>
  </div>
</template>

<style scoped>
.avatar-lg {
  width: 48px;
  height: 48px;
  font-size: 1.15rem;
}

.tier-badge {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.25rem 0.6rem;
  border-radius: 0.4rem;
  letter-spacing: 0.02em;
}

/* Reveal escalonado */
.bank-card {
  animation: revealUp 0.55s cubic-bezier(0.16, 1, 0.3, 1) both;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.bank-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08) !important;
}

@keyframes revealUp {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
