<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { advanceCdt, getCdt, type Cdt } from '../api/cdts'
import { createSignature } from '../api/signatures'
import { STAGES, stageIndex } from '../data/stages'
import { calcCdtDays, formatCOP } from '../utils/format'

const route = useRoute()
const router = useRouter()

const cdt = ref<Cdt | null>(null)
const loading = ref(true)
const advancing = ref(false)

// Estado mock de cada etapa (solo visual, no se persiste)
const form = ref({ fullName: '', docNumber: '', city: '' })
const docs = ref({ cedula: false, fondos: false })
const payMethod = ref<'pse' | 'transferencia'>('pse')

// Firma digital (proceso real en el servicio digital_signature)
const signEmail = ref('')
const signLink = ref('')
const sending = ref(false)
const signError = ref('')

const idx = computed(() => (cdt.value ? stageIndex(cdt.value.stage) : 0))
const gains = computed(() => {
  if (!cdt.value) return { interest: 0, final: 0 }
  return calcCdtDays(Number(cdt.value.amount), Number(cdt.value.rate), cdt.value.term)
})

const canContinue = computed(() => {
  if (!cdt.value) return false
  switch (cdt.value.stage) {
    case 'formularios': return !!(form.value.fullName && form.value.docNumber && form.value.city)
    case 'documentos': return docs.value.cedula && docs.value.fondos
    case 'pago': return true
    default: return false
  }
})

const ctaLabel = computed(() => {
  switch (cdt.value?.stage) {
    case 'formularios': return 'Guardar y continuar'
    case 'documentos': return 'Continuar a la firma'
    case 'pago': return `Pagar ${formatCOP(Number(cdt.value.amount))}`
    default: return ''
  }
})

async function sendSignLink() {
  if (!cdt.value || sending.value) return
  sending.value = true
  signError.value = ''
  try {
    const r = await createSignature({ cdt_id: cdt.value.id, email: signEmail.value.trim() })
    signLink.value = r.sign_url
  } catch (e: any) {
    signError.value = e.message || 'No pudimos enviar el enlace, intenta de nuevo'
  } finally {
    sending.value = false
  }
}

async function load() {
  try {
    cdt.value = await getCdt(route.params.id as string)
  } catch {
    router.replace('/dashboard')
  } finally {
    loading.value = false
  }
}

async function advance() {
  if (!cdt.value || advancing.value || !canContinue.value) return
  advancing.value = true
  try {
    cdt.value = await advanceCdt(cdt.value.id)
  } finally {
    advancing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="text-center py-5">
    <div class="spinner-border text-primary" role="status"></div>
  </div>

  <div v-else-if="cdt">
    <!-- Header -->
    <div class="d-flex flex-wrap justify-content-between align-items-center mb-4 gap-3">
      <div>
        <RouterLink to="/dashboard" class="text-decoration-none small fw-semibold">
          <i class="bi bi-arrow-left me-1"></i>Mis CDTs
        </RouterLink>
        <h3 class="fw-bolder mb-0 mt-1">Apertura de CDT #{{ cdt.id }}</h3>
      </div>
      <div class="d-flex gap-2 flex-wrap">
        <span class="badge text-bg-light border">{{ formatCOP(Number(cdt.amount)) }}</span>
        <span class="badge text-bg-light border">{{ cdt.term }} días</span>
        <span class="badge text-bg-light border">{{ Number(cdt.rate).toFixed(2) }}% E.A.</span>
      </div>
    </div>

    <!-- Stepper -->
    <div class="stepper mb-4">
      <template v-for="(s, i) in STAGES" :key="s.key">
        <div class="step" :class="{ done: i < idx, current: i === idx }">
          <div class="step-dot"><i class="bi" :class="i < idx ? 'bi-check-lg' : s.icon"></i></div>
          <div class="step-label">{{ s.label }}</div>
        </div>
        <div v-if="i < STAGES.length - 1" class="step-line" :class="{ done: i < idx }"></div>
      </template>
    </div>

    <div class="card shadow-sm mx-auto" style="max-width: 640px;">
      <div class="card-body p-4 p-lg-5">
        <!-- ETAPA: formularios -->
        <template v-if="cdt.stage === 'formularios'">
          <h5 class="fw-bold mb-1">Cuéntanos de ti</h5>
          <p class="text-body-secondary small mb-4">Necesitamos algunos datos básicos para abrir tu CDT.</p>
          <div class="mb-3">
            <label class="form-label small fw-semibold">Nombre completo</label>
            <input v-model="form.fullName" class="form-control" placeholder="Como aparece en tu documento" />
          </div>
          <div class="mb-3">
            <label class="form-label small fw-semibold">Número de documento</label>
            <input v-model="form.docNumber" class="form-control" placeholder="C.C." />
          </div>
          <div class="mb-3">
            <label class="form-label small fw-semibold">Ciudad de residencia</label>
            <input v-model="form.city" class="form-control" placeholder="Bogotá" />
          </div>
        </template>

        <!-- ETAPA: documentos -->
        <template v-else-if="cdt.stage === 'documentos'">
          <h5 class="fw-bold mb-1">Carga tus documentos</h5>
          <p class="text-body-secondary small mb-4">Los verificamos automáticamente en segundos.</p>
          <button
            type="button"
            class="upload-box mb-3"
            :class="{ uploaded: docs.cedula }"
            @click="docs.cedula = !docs.cedula"
          >
            <i class="bi" :class="docs.cedula ? 'bi-check-circle-fill' : 'bi-cloud-arrow-up'"></i>
            <div>
              <div class="fw-semibold">Cédula de ciudadanía</div>
              <div class="small text-body-secondary">{{ docs.cedula ? 'cedula.pdf — cargado' : 'PDF o imagen, ambas caras' }}</div>
            </div>
          </button>
          <button
            type="button"
            class="upload-box"
            :class="{ uploaded: docs.fondos }"
            @click="docs.fondos = !docs.fondos"
          >
            <i class="bi" :class="docs.fondos ? 'bi-check-circle-fill' : 'bi-cloud-arrow-up'"></i>
            <div>
              <div class="fw-semibold">Declaración de origen de fondos</div>
              <div class="small text-body-secondary">{{ docs.fondos ? 'declaracion.pdf — cargado' : 'Formato diligenciado y firmado' }}</div>
            </div>
          </button>
        </template>

        <!-- ETAPA: firma (proceso real por correo) -->
        <template v-else-if="cdt.stage === 'firma'">
          <h5 class="fw-bold mb-1">Firma tu contrato</h5>
          <p class="text-body-secondary small mb-4">
            Te enviaremos un enlace seguro a tu correo para validar tu identidad y firmar digitalmente.
          </p>
          <div class="border rounded-3 p-3 mb-3 d-flex align-items-center gap-3" style="background: #faf9fe;">
            <i class="bi bi-file-earmark-text fs-3" style="color: var(--brand);"></i>
            <div class="flex-grow-1">
              <div class="fw-semibold">Contrato de apertura CDT #{{ cdt.id }}</div>
              <div class="small text-body-secondary">{{ formatCOP(Number(cdt.amount)) }} · {{ cdt.term }} días · {{ Number(cdt.rate).toFixed(2) }}% E.A.</div>
            </div>
          </div>

          <template v-if="!signLink">
            <label class="form-label small fw-semibold">Correo electrónico</label>
            <input
              v-model="signEmail"
              type="email"
              class="form-control"
              placeholder="tu@correo.com"
              @keyup.enter="sendSignLink"
            />
            <button
              class="btn btn-primary w-100 mt-3"
              :disabled="!signEmail.includes('@') || sending"
              @click="sendSignLink"
            >
              <span v-if="sending" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-envelope-paper me-2"></i>Enviar enlace de firma
            </button>
            <div v-if="signError" class="alert alert-danger mt-3 mb-0">{{ signError }}</div>
          </template>

          <div v-else class="alert alert-success mb-0">
            <div class="d-flex align-items-center gap-2 mb-2">
              <i class="bi bi-envelope-check-fill"></i>
              <span>Enviamos el enlace de firma a <b>{{ signEmail }}</b>.</span>
            </div>
            <div class="small mb-2">Al completar la firma volverás aquí y tu CDT pasará a pago.</div>
            <a :href="signLink" class="btn btn-outline-primary btn-sm">
              Abrir firma ahora<i class="bi bi-box-arrow-up-right ms-2"></i>
            </a>
          </div>
        </template>

        <!-- ETAPA: pago -->
        <template v-else-if="cdt.stage === 'pago'">
          <h5 class="fw-bold mb-1">Fondea tu CDT</h5>
          <p class="text-body-secondary small mb-4">Elige cómo transferir {{ formatCOP(Number(cdt.amount)) }}.</p>
          <label class="upload-box mb-3" :class="{ uploaded: payMethod === 'pse' }">
            <input v-model="payMethod" type="radio" value="pse" class="d-none" />
            <i class="bi bi-lightning-charge"></i>
            <div>
              <div class="fw-semibold">PSE</div>
              <div class="small text-body-secondary">Débito inmediato desde tu banco</div>
            </div>
          </label>
          <label class="upload-box" :class="{ uploaded: payMethod === 'transferencia' }">
            <input v-model="payMethod" type="radio" value="transferencia" class="d-none" />
            <i class="bi bi-bank"></i>
            <div>
              <div class="fw-semibold">Transferencia bancaria</div>
              <div class="small text-body-secondary">Acreditación en 1 día hábil</div>
            </div>
          </label>
        </template>

        <!-- ETAPA: terminado -->
        <template v-else>
          <div class="text-center">
            <div class="empty-state-icon mb-3" style="background: linear-gradient(135deg, #dcfce7, #d1fae5); color: #059669;">
              <i class="bi bi-check-lg"></i>
            </div>
            <h4 class="fw-bolder mb-2">¡Tu CDT está activo!</h4>
            <p class="text-body-secondary mb-4">Tu inversión ya está trabajando por ti.</p>
            <div class="border rounded-3 p-4 text-start mb-4" style="background: #faf9fe;">
              <div class="d-flex justify-content-between mb-2">
                <span class="text-body-secondary">Invertiste</span>
                <span class="fw-bold">{{ formatCOP(Number(cdt.amount)) }}</span>
              </div>
              <div class="d-flex justify-content-between mb-2">
                <span class="text-body-secondary">Plazo · Tasa</span>
                <span class="fw-bold">{{ cdt.term }} días · {{ Number(cdt.rate).toFixed(2) }}% E.A.</span>
              </div>
              <div class="d-flex justify-content-between mb-2">
                <span class="text-body-secondary">Ganarás</span>
                <span class="fw-bold money-positive">+{{ formatCOP(gains.interest) }}</span>
              </div>
              <div class="d-flex justify-content-between">
                <span class="text-body-secondary">Recibirás al final</span>
                <span class="fw-bold">{{ formatCOP(gains.final) }}</span>
              </div>
            </div>
            <RouterLink to="/dashboard" class="btn btn-primary px-4">
              Ir a mi dashboard
            </RouterLink>
          </div>
        </template>

        <!-- CTA avanzar (la etapa firma avanza sola al confirmar el OTP) -->
        <button
          v-if="cdt.stage !== 'terminado' && cdt.stage !== 'firma'"
          class="btn btn-primary w-100 mt-4 py-2"
          :disabled="!canContinue || advancing"
          @click="advance"
        >
          <span v-if="advancing" class="spinner-border spinner-border-sm me-2"></span>
          {{ ctaLabel }}
          <i class="bi bi-arrow-right ms-2"></i>
        </button>
      </div>
    </div>
  </div>
</template>
