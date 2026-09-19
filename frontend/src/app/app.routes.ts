import { Routes } from '@angular/router';

import { requireAuth, requireGuest } from './core/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [requireGuest],
    loadComponent: () => import('./pages/login.component').then((m) => m.LoginComponent),
  },
  {
    path: 'register',
    canActivate: [requireGuest],
    loadComponent: () => import('./pages/register.component').then((m) => m.RegisterComponent),
  },
  {
    path: '',
    canActivate: [requireAuth],
    loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent),
  },
  { path: '**', redirectTo: '' },
];
