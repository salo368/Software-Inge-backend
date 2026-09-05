<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BANKS, TERMS, TIER_COLORS, type Bank, type TermKey, type Tier } from '../data/banks'
import { calcCdtDays, formatCOP } from '../utils/format'
import AnimatedMoney from '../components/AnimatedMoney.vue'

// --- Estado del simulador ---
const amount = ref<number>(5_000_000)
const term = ref<TermKey>('360')
const sortBy = ref<'yield' | 'safety'>('yield')
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

// Rango de tasas del mercado (para el glass card del hero, sin decir "ganador")
const marketMax = computed(() => Math.max(...BANKS.map((b) => b.rates[term.value])))
const marketMin = computed(() => Math.min(...BANKS.map((b) => b.rates[term.value])))

function onSimulate() {
  if (!isValid.value) return
  showResults.value = false
  requestAnimationFrame(() => { showResults.value = true })
}

watch(term, () => {
  if (!showResults.value) return
  showResults.value = false
  requestAnimationFrame(() => { showResults.value = true })
})
</script>

<template>
  <div>
    <!-- ============ HERO (compacto, entra en 1080p junto a los controles) ============ -->
    <section class="hero-dark p-4 px-lg-5 mb-0">
      <div class="row g-4 align-items-center position-relative" style="z-index: 1;">
        <div class="col-lg-7">
          <span class="hero-eyebrow">
            <i class="bi bi-lightning-charge-fill"></i>
            Simulador de CDT · Colombia
          </span>
          <h1 class="display-5 mt-3 mb-2">
            Tu dinero merece
            <span class="hero-highlight">crecer mejor.</span>
          </h1>
          <p class="mb-3" style="color: rgba(255,255,255,0.72); max-width: 36rem; font-size: 1.05rem;">
            Compara {{ BANKS.length }} entidades en segundos: tasas, plazos y solidez.
            Invierte con información, no con suposiciones.
          </p>
          <div class="d-flex flex-wrap gap-2">
            <span class="trust-chip"><i class="bi bi-shield-check"></i> Entidades vigiladas por la SFC</span>
            <span class="trust-chip"><i class="bi bi-bank"></i> Depósitos protegidos por Fogafín</span>
            <span class="trust-chip"><i class="bi bi-stars"></i> Comparación gratuita</span>
          </div>
        </div>

        <div class="col-lg-5">
          <div class="glass-card p-3 p-lg-4">
            <div class="glass-label mb-2">Tasas E.A. del mercado · {{ selectedTermLabel }}</div>
            <div class="row g-4 text-nowrap">
              <div class="col-6">
                <div class="glass-label mb-1">Desde</div>
                <div class="fs-2 fw-bold lh-1">{{ marketMin.toFixed(2) }}%</div>
              </div>
              <div class="col-6">
                <div class="glass-label mb-1">Hasta</div>
                <div class="fs-2 fw-bold lh-1" style="color:#a7f3d0;">{{ marketMax.toFixed(2) }}%</div>
              </div>
            </div>
            <hr class="my-3" style="border-color: rgba(255,255,255,0.14); opacity: 1;" />
            <div class="d-flex align-items-center gap-2 small" style="color: rgba(255,255,255,0.65);">
              <i class="bi bi-info-circle"></i>
              La diferencia entre elegir bien y elegir rápido puede ser millonaria.
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ CONTROLES (una sola fila: monto | plazo | CTA) ============ -->
    <div class="card shadow-sm mx-2 mx-lg-5 position-relative" style="margin-top: -2.5rem; z-index: 2;">
      <div class="card-body p-4">
        <div class="row g-3 justify-content-center align-items-end controls-row">
          <div class="col-12 col-lg-auto">
            <label class="form-label small text-uppercase text-body-secondary fw-bold d-block mb-2">
              <i class="bi bi-cash-stack me-1"></i>Monto a invertir
            </label>
            <div class="input-group amount-input">
              <span class="input-group-text">$</span>
              <input
                v-model.number="amount"
                type="number"
                class="form-control text-center"
                min="0"
                step="100000"
                placeholder="5.000.000"
              />
              <span class="input-group-text">COP</span>
            </div>
          </div>

          <div class="col-12 col-lg-auto">
            <label class="form-label small text-uppercase text-body-secondary fw-bold d-block mb-2">
              <i class="bi bi-calendar3 me-1"></i>Plazo
            </label>
            <div class="segmented">
              <button
                v-for="t in TERMS"
                :key="t.key"
                type="button"
                class="seg-item"
                :class="{ active: term === t.key }"
                @click="term = t.key"
              >
                {{ t.label }}
              </button>
            </div>
          </div>

          <div class="col-12 col-lg-auto">
            <button
              class="btn btn-primary px-4 cta-btn"
              :disabled="!isValid"
              @click="onSimulate"
            >
              {{ showResults ? 'Simular de nuevo' : 'Ver mis opciones' }}
              <i class="bi bi-arrow-right ms-2"></i>
            </button>
          </div>
        </div>

        <div class="text-center form-text mt-3 mb-0">
          = <span class="fw-semibold">{{ formatCOP(amount || 0) }}</span>
          · cada entidad ofrece tasas distintas según el plazo, pruébalos todos
        </div>
      </div>
    </div>

    <!-- ============ EMPTY STATE ============ -->
    <div v-if="!showResults" class="text-center py-4 my-2">
      <div class="empty-state-icon mb-3">
        <i class="bi bi-graph-up-arrow"></i>
      </div>
      <h5 class="fw-bold mb-2">Listo cuando tú lo estés</h5>
      <p class="text-body-secondary mb-0" style="max-width: 26rem; margin-inline: auto;">
        Ajusta el monto y el plazo, y presiona
        <span class="fw-semibold text-body">Ver mis opciones</span> para descubrir
        cuánto puede crecer tu inversión en cada entidad.
      </p>
    </div>

    <!-- ============ RESULTADOS ============ -->
    <template v-else>
      <div class="d-flex flex-wrap justify-content-between align-items-center mt-4 mb-3 gap-2">
        <div>
          <h5 class="mb-1 fw-bold">{{ BANKS.length }} entidades aliadas</h5>
          <div class="text-body-secondary small">
            Simulando <span class="fw-semibold">{{ formatCOP(amount || 0) }}</span>
            a <span class="fw-semibold">{{ selectedTermLabel }}</span>
          </div>
        </div>
        <div class="d-flex align-items-center gap-2">
          <label class="text-body-secondary small mb-0 fw-semibold">Ordenar por</label>
          <select v-model="sortBy" class="form-select form-select-sm fw-semibold" style="width: auto;">
            <option value="yield">Mayor rentabilidad</option>
            <option value="safety">Mayor solidez</option>
          </select>
        </div>
      </div>

      <div class="row g-3">
        <div
          v-for="(row, idx) in results"
          :key="row.id"
          class="col-12 col-md-6 col-xl-4"
        >
          <div class="card h-100 shadow-sm bank-card" :style="{ animationDelay: `${idx * 55}ms` }">
            <div class="card-body p-4 d-flex flex-column">
              <!-- Header (min-height fija para que las cards vecinas queden parejas) -->
              <div class="d-flex align-items-center gap-3 mb-3 bank-card-header">
                <div class="bank-logo">
                  <img :src="row.logo" :alt="row.name" loading="lazy" />
                </div>
                <div class="flex-grow-1">
                  <div class="fw-bold lh-sm">{{ row.name }}</div>
                  <div
                    class="tier-badge mt-1"
                    :style="{ background: TIER_COLORS[row.tier].bg, color: TIER_COLORS[row.tier].fg }"
                    :title="`${TIER_COLORS[row.tier].label} — según ${row.ratingBy}`"
                  >
                    <i class="bi bi-shield-fill-check"></i>
                    {{ row.tier }} · {{ TIER_COLORS[row.tier].label }}
                  </div>
                </div>
              </div>

              <!-- Highlights -->
              <ul class="list-unstyled small text-body-secondary mb-3 flex-grow-1">
                <li v-for="h in row.highlights" :key="h" class="mb-1 d-flex align-items-start gap-2">
                  <i class="bi bi-check-circle-fill mt-1" style="color:#a78bfa; font-size: 0.75rem;"></i>
                  <span>{{ h }}</span>
                </li>
              </ul>

              <!-- Tasa + ganancia (labels arriba alineados, cifras abajo alineadas) -->
              <div class="d-flex align-items-stretch justify-content-between border-top pt-3">
                <div class="d-flex flex-column justify-content-between">
                  <div class="text-body-secondary small fw-semibold">Tasa E.A.</div>
                  <div class="fs-3 fw-bolder rate-gradient lh-1 mt-2">
                    {{ row.rate.toFixed(2) }}<span class="fs-6">%</span>
                  </div>
                </div>
                <div class="d-flex flex-column justify-content-between text-end">
                  <div class="text-body-secondary small fw-semibold">Ganarías</div>
                  <div class="fs-5 fw-bold money-positive lh-1 mt-2">
                    <AnimatedMoney :value="row.interest" prefix="+" />
                  </div>
                </div>
              </div>

              <!-- Detalles -->
              <div class="mt-3 pt-3 border-top small">
                <div class="d-flex justify-content-between mb-1">
                  <span class="text-body-secondary">Recibirías al final</span>
                  <span class="fw-bold"><AnimatedMoney :value="row.final" /></span>
                </div>
                <div class="d-flex justify-content-between">
                  <span class="text-body-secondary">Inversión mínima</span>
                  <span class="fw-semibold">{{ formatCOP(row.minAmount) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <p class="text-body-secondary small mt-4 mb-5">
        <i class="bi bi-info-circle me-1"></i>
        Simulación referencial. Las tasas y calificaciones mostradas son ejemplos y no
        representan ofertas vigentes. Verifica las condiciones con cada entidad y ten en
        cuenta la retención en la fuente (4% sobre intereses).
      </p>
    </template>
  </div>
</template>
