<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  confirmOtp, getProcess, getUploadUrl, putFile, requestOtp, validatePhoto,
  type SignProcess, type UploadType,
} from '../api'
import CameraCapture from '../components/CameraCapture.vue'
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

// --- Identidad (3 capturas con camara, sin subida de archivos) ---
type CamMode = 'document' | 'face'
const DOCS: { type: UploadType; label: string; short: string; hint: string; icon: string; mode: CamMode }[] = [
  { type: 'cedula_front', label: 'Cédula — cara frontal', short: 'Cédula frontal', hint: 'Centra el frente de tu cédula dentro del recuadro', icon: 'bi-person-vcard', mode: 'document' },
  { type: 'cedula_back', label: 'Cédula — cara posterior', short: 'Cédula posterior', hint: 'Ahora la cara posterior, que se lea el código', icon: 'bi-person-vcard-fill', mode: 'document' },
  { type: 'face', label: 'Foto de tu rostro', short: 'Tu rostro', hint: 'Ubica tu rostro dentro del óvalo, con buena luz', icon: 'bi-emoji-smile', mode: 'face' },
]
const docDone = ref<Record<UploadType, boolean>>({
  cedula_front: false, cedula_back: false, face: false, signature: false,
})
const currentDoc = ref<UploadType | ''>('')
const uploadBusy = ref(false)
const camRef = ref<InstanceType<typeof CameraCapture>>()
const allDocsDone = computed(() => docDone.value.cedula_front && docDone.value.cedula_back && docDone.value.face)
const activeDoc = computed(() => DOCS.find((d) => d.type === currentDoc.value))

function nextPendingDoc(): UploadType | '' {
  return DOCS.find((d) => !docDone.value[d.type])?.type ?? ''
}

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
    currentDoc.value = nextPendingDoc()
    if (p.stage === 'firmado') step.value = 'done'
    else if (p.stage === 'otp') { step.value = 'otp'; otpSent.value = false }
    else if (p.stage === 'dibujo') step.value = 'dibujo'
    else if (p.stage === 'documentos') step.value = 'documentos'
    else step.value = 'revision'
    poll = window.setInterval(syncProcess, 4000)
  } catch {
    notFound.value = true
  }
})
onUnmounted(() => window.clearInterval(poll))

// Sincroniza con el proceso real: fotos o avances hechos desde otro
// dispositivo se reflejan aqui sin recargar (solo avanza, nunca retrocede)
const STEP_ORDER: Record<Step, number> = { revision: 0, documentos: 1, dibujo: 2, otp: 3, done: 4 }
const STAGE_ORDER: Record<string, number> = { revision: 0, documentos: 1, dibujo: 2, otp: 3, firmado: 4 }
let poll: number | undefined

async function syncProcess() {
  if (notFound.value || !process.value || busy.value || uploadBusy.value || step.value === 'done') return
  try {
    const p = await getProcess(token)
    docDone.value = { ...p.uploads }
    if (step.value === 'documentos' && !currentDoc.value) currentDoc.value = nextPendingDoc()
    if ((STAGE_ORDER[p.stage] ?? 0) > STEP_ORDER[step.value]) {
      if (p.stage === 'firmado') {
        step.value = 'done'
        setTimeout(() => { window.location.href = returnUrl.value }, 6000)
      } else {
        step.value = p.stage
        if (p.stage === 'otp') otpSent.value = true
      }
    }
  } catch {
    /* reintenta en el proximo tick */
  }
}

async function onCaptured(blob: Blob) {
  const type = currentDoc.value
  if (!type || uploadBusy.value) return
  uploadBusy.value = true
  error.value = ''
  try {
    const { upload_url } = await getUploadUrl(token, type, 'image/jpeg')
    await putFile(upload_url, blob, 'image/jpeg')
    const v = await validatePhoto(token, type)
    if (!v.valid) {
      docDone.value[type] = false
      error.value = 'No pudimos validar la foto. Tómala de nuevo con buena luz y sin reflejos.'
      camRef.value?.reset()
      return
    }
    docDone.value[type] = true
    currentDoc.value = nextPendingDoc()
    camRef.value?.reset()
  } catch (e: any) {
    error.value = e.message || 'Error subiendo la foto'
  } finally {
    uploadBusy.value = false
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

    <!-- PASO: identidad (captura guiada con camara, sin subir archivos) -->
    <div v-else-if="step === 'documentos'" class="card shadow-sm">
      <div class="card-body p-4">
        <h5 class="fw-bold mb-1">Valida tu identidad</h5>
        <p class="text-body-secondary small mb-3">
          Tomaremos 3 fotos con la cámara de tu dispositivo. No se permiten archivos.
        </p>

        <div class="d-flex gap-2 mb-3">
          <button
            v-for="d in DOCS"
            :key="d.type"
            type="button"
            class="doc-chip"
            :class="{ done: docDone[d.type], active: currentDoc === d.type }"
            :disabled="uploadBusy"
            @click="currentDoc = d.type"
          >
            <i class="bi" :class="docDone[d.type] ? 'bi-check-circle-fill' : d.icon"></i>
            <span>{{ d.short }}</span>
          </button>
        </div>

        <template v-if="activeDoc">
          <div class="fw-semibold mb-1">{{ activeDoc.label }}</div>
          <p class="text-body-secondary small mb-3">{{ activeDoc.hint }}</p>
          <CameraCapture
            ref="camRef"
            :key="activeDoc.type"
            :mode="activeDoc.mode"
            :busy="uploadBusy"
            @captured="onCaptured"
          />
        </template>

        <div v-else class="cam-error text-center p-4">
          <i class="bi bi-check-circle-fill fs-2 d-block mb-2" style="color: #059669;"></i>
          <p class="small mb-0">
            Las 3 fotos quedaron listas. Toca cualquiera arriba si quieres repetirla.
          </p>
        </div>

        <button class="btn btn-primary w-100 mt-3 py-2" :disabled="!allDocsDone || uploadBusy" @click="step = 'dibujo'">
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
