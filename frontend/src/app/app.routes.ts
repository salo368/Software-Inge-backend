import { Routes } from '@angular/router';

import { requireAuth, requireGuest } from './core/auth.guard';

export const routes: Routes = [
  {
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
    // Public docs section. Hidden: not linked from the UI.
    path: 'docs',
    loadChildren: () => import('./pages/docs/docs.routes').then((m) => m.DOCS_ROUTES),
  },
  {
    path: 'me',
    canActivate: [requireAuth],
    loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent),
  },
  {
    path: 'process/:id',
    canActivate: [requireAuth],
    loadComponent: () => import('./pages/process.component').then((m) => m.ProcessComponent),
  },
  {
    // Public on purpose: the token in the URL is the credential, so the link
    // works from the email on any device without a session.
    path: 'firmar/:token',
    loadComponent: () => import('./pages/sign.component').then((m) => m.SignComponent),
  },
  { path: '**', redirectTo: '' },
];
