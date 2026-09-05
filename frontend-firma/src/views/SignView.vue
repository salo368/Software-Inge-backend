<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  confirmOtp, getProcess, getUploadUrl, putFile, requestOtp,
  type SignProcess, type UploadType,
} from '../api'
import PdfPreview from '../components/PdfPreview.vue'
import SignaturePad from '../components/SignaturePad.vue'

const route = useRoute()
const token = route.params.token as string

type Step = 'revision' | 'documentos' | 'dibujo' | 'otp' | 'done'

const STEPS: { key: Step; label: string; icon: string }[] = [
  { key: 'revision', label: 'Revisión', icon: 'bi-file-earmark-text' },
  { key: 'documentos', label: 'Identidad', icon: 'bi-person-badge' },
  { key: 'dibujo', label: 'Firma', icon: 'bi-pen' },
  { key: 'otp', label: 'Código', icon: 'bi-envelope-check' },
]

const process = ref<SignProcess | null>(null)
const notFound = ref(false)
const step = ref<Step>('revision')
const error = ref('')
const busy = ref(false)

const stepIdx = computed(() => STEPS.findIndex((s) => s.key === step.value))

// --- Identidad (3 fotos) ---
const DOCS: { type: UploadType; label: string; hint: string; icon: string }[] = [
  { type: 'cedula_front', label: 'Cédula — cara frontal', hint: 'Foto nítida, sin reflejos', icon: 'bi-person-vcard' },
  { type: 'cedula_back', label: 'Cédula — cara posterior', hint: 'Que se lea el código', icon: 'bi-person-vcard-fill' },
  { type: 'face', label: 'Foto de tu rostro', hint: 'De frente, buena luz', icon: 'bi-emoji-smile' },
]
const docDone = ref<Record<UploadType, boolean>>({
  cedula_front: false, cedula_back: false, face: false, signature: false,
})
const docBusy = ref<UploadType | ''>('')
const allDocsDone = computed(() => docDone.value.cedula_front && docDone.value.cedula_back && docDone.value.face)

// --- Firma dibujada ---
const sigBlob = ref<Blob | null>(null)

// --- OTP ---
const otp = ref('')
const otpSent = ref(false)
const returnUrl = ref('')
const signedPdfUrl = ref('')

onMounted(async () => {
  try {
    const p = await getProcess(token)
    process.value = p
    returnUrl.value = p.return_url
    docDone.value = { ...p.uploads }
    if (p.stage === 'firmado') step.value = 'done'
    else if (p.stage === 'otp') { step.value = 'otp'; otpSent.value = false }
    else if (p.stage === 'dibujo') step.value = 'dibujo'
    else if (p.stage === 'documentos') step.value = 'documentos'
    else step.value = 'revision'
  } catch {
    notFound.value = true
  }
})

async function uploadDoc(type: UploadType, ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const ctype = file.type === 'image/png' ? 'image/png' : 'image/jpeg'
  docBusy.value = type
  error.value = ''
  try {
    const { upload_url } = await getUploadUrl(token, type, ctype)
    await putFile(upload_url, file, ctype)
    docDone.value[type] = true
  } catch (e: any) {
    error.value = e.message || 'Error subiendo el archivo'
  } finally {
    docBusy.value = ''
  }
}

async function submitSignature() {
  if (!sigBlob.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { upload_url } = await getUploadUrl(token, 'signature', 'image/png')
    await putFile(upload_url, sigBlob.value, 'image/png')
    await requestOtp(token)
    otpSent.value = true
    step.value = 'otp'
  } catch (e: any) {
    error.value = e.message || 'Error enviando la firma'
  } finally {
    busy.value = false
  }
}

async function resendOtp() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await requestOtp(token)
    otpSent.value = true
  } catch (e: any) {
    error.value = e.message || 'Error enviando el código'
  } finally {
    busy.value = false
  }
}

async function confirm() {
  if (otp.value.length !== 6 || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const r = await confirmOtp(token, otp.value)
    returnUrl.value = r.return_url
    signedPdfUrl.value = r.signed_pdf_url
    step.value = 'done'
    setTimeout(() => { window.location.href = r.return_url }, 6000)
  } catch (e: any) {
    error.value = e.code === 'invalid_otp'
      ? `Código incorrecto. ${e.message}`
      : (e.message || 'Error confirmando el código')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <!-- Enlace inválido -->
  <div v-if="notFound" class="text-center py-5">
    <div class="empty-state-icon mb-3"><i class="bi bi-link-45deg"></i></div>
    <h5 class="fw-bold mb-2">Enlace no válido</h5>
    <p class="text-body-secondary mb-0">Este enlace de firma no existe o expiró.</p>
  </div>

  <div v-else-if="!process" class="text-center py-5">
    <div class="spinner-border text-primary" role="status"></div>
  </div>

  <div v-else class="mx-auto" style="max-width: 720px;">
    <!-- Mini stepper -->
    <div v-if="step !== 'done'" class="stepper mb-4">
      <template v-for="(s, i) in STEPS" :key="s.key">
        <div class="step" :class="{ done: i < stepIdx, current: i === stepIdx }">
          <div class="step-dot"><i class="bi" :class="i < stepIdx ? 'bi-check-lg' : s.icon"></i></div>
          <div class="step-label">{{ s.label }}</div>
        </div>
        <div v-if="i < STEPS.length - 1" class="step-line" :class="{ done: i < stepIdx }"></div>
      </template>
    </div>

    <div v-if="error" class="alert alert-danger d-flex align-items-center gap-2">
      <i class="bi bi-exclamation-triangle-fill"></i>{{ error }}
    </div>

    <!-- PASO: revisión -->
    <div v-if="step === 'revision'" class="card shadow-sm">
      <div class="card-body p-4">
        <h5 class="fw-bold mb-1">Revisa tu documento</h5>
        <p class="text-body-secondary small mb-3">
          Este es el contrato que vas a firmar. El recuadro marca dónde quedará tu firma.
        </p>
        <PdfPreview :pdf-url="process.pdf_url" :page="process.page" :x="process.x" :y="process.y" />
        <button class="btn btn-primary w-100 mt-4 py-2" @click="step = 'documentos'">
          Todo en orden, continuar<i class="bi bi-arrow-right ms-2"></i>
        </button>
      </div>
    </div>

    <!-- PASO: identidad -->
    <div v-else-if="step === 'documentos'" class="card shadow-sm">
      <div class="card-body p-4">
        <h5 class="fw-bold mb-1">Valida tu identidad</h5>
        <p class="text-body-secondary small mb-3">Necesitamos 3 fotos para verificar que eres tú.</p>

        <label v-for="d in DOCS" :key="d.type" class="upload-box mb-3" :class="{ uploaded: docDone[d.type] }">
          <input type="file" accept="image/*" class="d-none" :disabled="docBusy === d.type" @change="uploadDoc(d.type, $event)" />
          <span v-if="docBusy === d.type" class="spinner-border spinner-border-sm" style="color: var(--brand);"></span>
          <i v-else class="bi" :class="docDone[d.type] ? 'bi-check-circle-fill' : d.icon"></i>
          <div>
            <div class="fw-semibold">{{ d.label }}</div>
            <div class="small text-body-secondary">{{ docDone[d.type] ? 'Cargada — toca para reemplazar' : d.hint }}</div>
          </div>
        </label>

        <button class="btn btn-primary w-100 mt-2 py-2" :disabled="!allDocsDone" @click="step = 'dibujo'">
          Continuar a la firma<i class="bi bi-arrow-right ms-2"></i>
        </button>
      </div>
    </div>

    <!-- PASO: dibujo -->
    <div v-else-if="step === 'dibujo'" class="card shadow-sm">
      <div class="card-body p-4">
        <h5 class="fw-bold mb-1">Dibuja tu firma</h5>
        <p class="text-body-secondary small mb-3">Así quedará estampada en el documento.</p>
        <SignaturePad @change="sigBlob = $event" />
        <button class="btn btn-primary w-100 mt-4 py-2" :disabled="!sigBlob || busy" @click="submitSignature">
          <span v-if="busy" class="spinner-border spinner-border-sm me-2"></span>
          Usar esta firma<i class="bi bi-arrow-right ms-2"></i>
        </button>
      </div>
    </div>

    <!-- PASO: otp -->
    <div v-else-if="step === 'otp'" class="card shadow-sm">
      <div class="card-body p-4 text-center">
        <h5 class="fw-bold mb-1">Confirma con tu código</h5>
        <p class="text-body-secondary small mb-4">
          {{ otpSent ? 'Enviamos' : 'Te enviaremos' }} un código de 6 dígitos a
          <span class="fw-semibold">{{ process.email_masked }}</span>
        </p>

        <template v-if="otpSent">
          <input
            v-model="otp"
            class="form-control otp-input mb-3"
            maxlength="6"
            inputmode="numeric"
            autocomplete="one-time-code"
            placeholder="······"
          />
          <button class="btn btn-primary w-100 py-2" :disabled="otp.length !== 6 || busy" @click="confirm">
            <span v-if="busy" class="spinner-border spinner-border-sm me-2"></span>
            Firmar documento
          </button>
          <button class="btn btn-link btn-sm mt-2 text-decoration-none" :disabled="busy" @click="resendOtp">
            Reenviar código
          </button>
        </template>
        <button v-else class="btn btn-primary w-100 py-2" :disabled="busy" @click="resendOtp">
          <span v-if="busy" class="spinner-border spinner-border-sm me-2"></span>
          Enviar código a mi correo
        </button>
      </div>
    </div>

    <!-- PASO: done -->
    <div v-else class="card shadow-sm">
      <div class="card-body p-5 text-center">
        <div class="empty-state-icon mb-3" style="background: linear-gradient(135deg, #dcfce7, #d1fae5); color: #059669;">
          <i class="bi bi-patch-check-fill"></i>
        </div>
        <h4 class="fw-bolder mb-2">¡Documento firmado!</h4>
        <p class="text-body-secondary mb-4">
          Tu firma quedó estampada en el contrato. Te devolveremos al comercio en unos segundos.
        </p>
        <div class="d-flex justify-content-center gap-2 flex-wrap">
          <a v-if="signedPdfUrl" :href="signedPdfUrl" target="_blank" class="btn btn-outline-primary">
            <i class="bi bi-file-earmark-pdf me-1"></i>Ver documento firmado
          </a>
          <a :href="returnUrl" class="btn btn-primary px-4">
            Volver al comercio<i class="bi bi-arrow-right ms-2"></i>
          </a>
        </div>
      </div>
    </div>
  </div>
</template>
