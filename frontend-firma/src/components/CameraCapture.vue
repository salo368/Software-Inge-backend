<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

// mode document: camara trasera (movil) + guia rectangular horizontal (proporcion cedula)
// mode face: camara frontal + guia ovalada vertical
const props = defineProps<{ mode: 'document' | 'face'; busy?: boolean }>()
const emit = defineEmits<{ (e: 'captured', blob: Blob): void }>()

const CARD_RATIO = 1.586 // ISO ID-1 (85.6 x 54 mm)

const video = ref<HTMLVideoElement>()
const wrap = ref<HTMLDivElement>()
const guide = ref<HTMLDivElement>()
const stream = ref<MediaStream | null>(null)
const camError = ref(false)
const shot = ref<Blob | null>(null)
const shotUrl = ref('')

async function start() {
  stopStream()
  camError.value = false
  try {
    stream.value = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: props.mode === 'face' ? 'user' : 'environment',
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    })
    if (video.value) video.value.srcObject = stream.value
  } catch {
    camError.value = true
  }
}

function stopStream() {
  stream.value?.getTracks().forEach((t) => t.stop())
  stream.value = null
}

function discard() {
  if (shotUrl.value) URL.revokeObjectURL(shotUrl.value)
  shot.value = null
  shotUrl.value = ''
}

function retake() {
  discard()
  start()
}

function capture() {
  const v = video.value
  const w = wrap.value
  const g = guide.value
  if (!v || !w || !g || !v.videoWidth) return

  // Mapea la guia (coordenadas de pantalla) a pixeles del video (object-fit: cover)
  const wr = w.getBoundingClientRect()
  const gr = g.getBoundingClientRect()
  const scale = Math.max(wr.width / v.videoWidth, wr.height / v.videoHeight)
  const offX = (v.videoWidth * scale - wr.width) / 2
  const offY = (v.videoHeight * scale - wr.height) / 2
  let sx = (gr.left - wr.left + offX) / scale
  const sy = (gr.top - wr.top + offY) / scale
  const sw = gr.width / scale
  const sh = gr.height / scale

  const mirrored = props.mode === 'face'
  if (mirrored) sx = v.videoWidth - sx - sw

  // Salida fija: documento horizontal, rostro vertical
  const outW = props.mode === 'document' ? 1280 : 900
  const outH = props.mode === 'document' ? Math.round(1280 / CARD_RATIO) : 1200
  const canvas = document.createElement('canvas')
  canvas.width = outW
  canvas.height = outH
  const ctx = canvas.getContext('2d')!
  if (mirrored) {
    ctx.translate(outW, 0)
    ctx.scale(-1, 1)
  }
  ctx.drawImage(v, sx, sy, sw, sh, 0, 0, outW, outH)
  canvas.toBlob(
    (b) => {
      if (!b) return
      discard()
      shot.value = b
      shotUrl.value = URL.createObjectURL(b)
      stopStream()
    },
    'image/jpeg',
    0.92,
  )
}

function confirmShot() {
  if (shot.value && !props.busy) emit('captured', shot.value)
}

function reset() {
  retake()
}
defineExpose({ reset })

watch(() => props.mode, retake)
onMounted(start)
onBeforeUnmount(() => {
  stopStream()
  discard()
})
</script>

<template>
  <div>
    <!-- Foto capturada: confirmar o repetir -->
    <div v-if="shotUrl">
      <div class="text-center">
        <img :src="shotUrl" class="cam-shot" :class="mode" alt="Foto capturada" />
      </div>
      <div class="d-flex gap-2 mt-3">
        <button class="btn btn-outline-secondary w-50" :disabled="busy" @click="retake">
          <i class="bi bi-arrow-counterclockwise me-1"></i>Repetir
        </button>
        <button class="btn btn-primary w-50" :disabled="busy" @click="confirmShot">
          <span v-if="busy" class="spinner-border spinner-border-sm me-2"></span>
          Usar esta foto
        </button>
      </div>
    </div>

    <!-- Camara en vivo con guia -->
    <template v-else>
      <div v-if="camError" class="cam-error text-center p-4">
        <i class="bi bi-camera-video-off fs-2 d-block mb-2"></i>
        <p class="small mb-3">
          No pudimos acceder a la cámara. Revisa los permisos del navegador e inténtalo de nuevo.
        </p>
        <button class="btn btn-outline-primary btn-sm" @click="start">Reintentar</button>
      </div>
      <template v-else>
        <div ref="wrap" class="cam-wrap" :class="mode">
          <video ref="video" autoplay playsinline muted :class="{ mirror: mode === 'face' }"></video>
          <div ref="guide" class="cam-guide" :class="mode"></div>
        </div>
        <button class="btn btn-primary w-100 mt-3" @click="capture">
          <i class="bi bi-camera me-2"></i>Tomar foto
        </button>
      </template>
    </template>
  </div>
</template>
