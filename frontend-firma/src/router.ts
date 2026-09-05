import { createRouter, createWebHistory } from 'vue-router'
import SignView from './views/SignView.vue'
import NotFoundView from './views/NotFoundView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/s/:token', name: 'sign', component: SignView },
    { path: '/:pathMatch(.*)*', name: 'notfound', component: NotFoundView },
  ],
})
