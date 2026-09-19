import { Routes } from '@angular/router';

import { requireAuth, requireGuest } from './core/auth.guard';

export const routes: Routes = [
  {
    // Simulador publico. Landing.
    path: '',
    loadComponent: () => import('./pages/simulator.component').then((m) => m.SimulatorComponent),
  },
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
    // Seccion escondida de documentacion. Publica, no linkeada en el UI.
    path: 'docs',
    loadChildren: () => import('./pages/docs/docs.routes').then((m) => m.DOCS_ROUTES),
  },
  {
    // Mi cuenta (dashboard privado).
    path: 'me',
    canActivate: [requireAuth],
    loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent),
  },
  { path: '**', redirectTo: '' },
];
