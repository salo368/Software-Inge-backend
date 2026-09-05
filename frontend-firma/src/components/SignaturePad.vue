<script setup lang="ts">
import { onMounted, ref } from 'vue'

const emit = defineEmits<{ (e: 'change', blob: Blob | null): void }>()

const canvasEl = ref<HTMLCanvasElement>()
const hasInk = ref(false)
let ctx: CanvasRenderingContext2D
let drawing = false

function pos(e: PointerEvent) {
  const c = canvasEl.value!
  const r = c.getBoundingClientRect()
  return {
    x: (e.clientX - r.left) * (c.width / r.width),
    y: (e.clientY - r.top) * (c.height / r.height),
  }
}

function down(e: PointerEvent) {
  drawing = true
  canvasEl.value!.setPointerCapture(e.pointerId)
  const p = pos(e)
  ctx.beginPath()
  ctx.moveTo(p.x, p.y)
}

function move(e: PointerEvent) {
  if (!drawing) return
  const p = pos(e)
  ctx.lineTo(p.x, p.y)
  ctx.stroke()
  hasInk.value = true
}

function up() {
  if (!drawing) return
  drawing = false
  if (hasInk.value) {
    canvasEl.value!.toBlob((b) => emit('change', b), 'image/png')
  }
}

function clear() {
  const c = canvasEl.value!
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, c.width, c.height)
  ctx.strokeStyle = '#17143a'
  ctx.lineWidth = 3.5
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  hasInk.value = false
  emit('change', null)
}

onMounted(() => {
  ctx = canvasEl.value!.getContext('2d')!
  clear()
})
</script>

<template>
  <div>
    <canvas
      ref="canvasEl"
      width="900"
      height="300"
      class="sig-pad"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
    ></canvas>
    <div class="d-flex justify-content-between align-items-center mt-2">
      <span class="small text-body-secondary">Dibuja tu firma con el dedo o el mouse</span>
      <button type="button" class="btn btn-outline-secondary btn-sm" @click="clear">
        <i class="bi bi-eraser me-1"></i>Limpiar
      </button>
    </div>
  </div>
</template>
