<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { formatCOP } from '../utils/format'

const props = defineProps<{ value: number; duration?: number; prefix?: string }>()

const display = ref(0)
let raf = 0

function animate(to: number) {
  cancelAnimationFrame(raf)
  const from = display.value
  const start = performance.now()
  const dur = props.duration ?? 850
  const ease = (t: number) => 1 - Math.pow(1 - t, 3)

  const step = (now: number) => {
    const p = Math.min((now - start) / dur, 1)
    display.value = from + (to - from) * ease(p)
    if (p < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}

onMounted(() => animate(props.value))
watch(() => props.value, (v) => animate(v))
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <span>{{ (prefix ?? '') + formatCOP(Math.round(display)) }}</span>
</template>
