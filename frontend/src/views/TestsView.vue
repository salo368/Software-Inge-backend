<script setup lang="ts">
import { ref } from 'vue'
import FunctionalPanel from '../components/qa/FunctionalPanel.vue'
import LoadPanel from '../components/qa/LoadPanel.vue'

const tab = ref<'func' | 'load'>('func')
</script>

<template>
  <div class="qa-shell">
    <!-- Barra propia: esta herramienta se presenta como un producto aparte -->
    <header class="qa-topbar">
      <div class="qa-container d-flex align-items-center gap-3 py-3">
        <span class="qa-brand"><span class="qa-dot"></span>QA&nbsp;Console</span>
        <nav class="qa-tabs d-none d-sm-flex">
          <button :class="{ active: tab === 'func' }" @click="tab = 'func'">
            <i class="bi bi-clipboard2-check me-1"></i>Funcionales
          </button>
          <button :class="{ active: tab === 'load' }" @click="tab = 'load'">
            <i class="bi bi-speedometer2 me-1"></i>Carga
          </button>
        </nav>
        <span class="qa-env ms-auto">ambiente&nbsp;·&nbsp;dev</span>
      </div>
      <div class="qa-container d-flex d-sm-none pb-2">
        <nav class="qa-tabs">
          <button :class="{ active: tab === 'func' }" @click="tab = 'func'">
            <i class="bi bi-clipboard2-check me-1"></i>Funcionales
          </button>
          <button :class="{ active: tab === 'load' }" @click="tab = 'load'">
            <i class="bi bi-speedometer2 me-1"></i>Carga
          </button>
        </nav>
      </div>
    </header>

    <div class="qa-container py-4">
      <FunctionalPanel v-if="tab === 'func'" />
      <LoadPanel v-else />
    </div>
  </div>
</template>
