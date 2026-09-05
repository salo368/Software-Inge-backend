<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{ pdfUrl: string; page: number; x: number; y: number }>()

const wrap = ref<HTMLDivElement>()
const canvasEl = ref<HTMLCanvasElement>()
const ready = ref(false)
const failed = ref(false)

onMounted(async () => {
  try {
    const doc = await pdfjs.getDocument(props.pdfUrl).promise
    const page = await doc.getPage(props.page)
    const containerW = wrap.value!.clientWidth
    const base = page.getViewport({ scale: 1 })
    const scale = (containerW / base.width) * (window.devicePixelRatio || 1)
    const viewport = page.getViewport({ scale })
    const canvas = canvasEl.value!
    canvas.width = viewport.width
    canvas.height = viewport.height
    await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise
    ready.value = true
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <div ref="wrap" class="pdf-wrap">
    <div v-if="!ready && !failed" class="text-center py-5">
      <div class="spinner-border text-primary" role="status"></div>
    </div>
    <div v-if="failed" class="text-center py-5 text-body-secondary small">
      No se pudo cargar la vista previa del documento.
    </div>
    <canvas v-show="ready" ref="canvasEl"></canvas>
    <div v-if="ready" class="sig-box" :style="{ left: `${x}%`, top: `${y}%`, width: '28%' }">
      <i class="bi bi-pen"></i> Tu firma irá aquí
    </div>
  </div>
</template>
