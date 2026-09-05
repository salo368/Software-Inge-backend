<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <nav class="app-navbar sticky-top">
    <div class="container-xxl px-3 px-lg-4 d-flex align-items-center justify-content-between py-2">
      <span class="navbar-brand mb-0 fs-4">
        <span class="brand-gradient">CDT</span>s
        <span class="text-body-secondary fw-semibold fs-6 ms-2">Firma digital</span>
      </span>
      <span class="badge text-bg-light border fw-semibold">
        <i class="bi bi-shield-lock-fill me-1" style="color: var(--brand);"></i>
        Proceso seguro
      </span>
    </div>
  </nav>

  <main class="container-xxl px-3 px-lg-4 py-4 flex-grow-1 w-100">
    <RouterView />
  </main>

  <footer class="app-footer">
    <div class="container-xxl px-3 px-lg-4 py-3 d-flex flex-wrap justify-content-between align-items-center gap-2">
      <span class="footer-brand"><span style="color:#a78bfa;">CDT</span>s · Firma digital</span>
      <span class="small">Tus documentos viajan cifrados y solo se usan para validar tu identidad.</span>
    </div>
  </footer>
</template>
