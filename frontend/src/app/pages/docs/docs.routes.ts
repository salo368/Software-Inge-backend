import { Routes } from '@angular/router';

// Children of /docs, all lazy-loaded. Services and use-cases reuse the same
// component when only the params change (default Angular RouteReuseStrategy).
export const DOCS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () => import('./docs-shell.component').then((m) => m.DocsShellComponent),
    children: [
      {
        path: '',
        pathMatch: 'full',
        loadComponent: () => import('./overview.component').then((m) => m.OverviewComponent),
      },
      {
        path: 'services',
        loadComponent: () => import('./services.component').then((m) => m.ServicesComponent),
      },
      {
        path: 'services/:serviceId',
        loadComponent: () => import('./services.component').then((m) => m.ServicesComponent),
      },
      {
        path: 'services/:serviceId/scenarios/:scenarioId',
        loadComponent: () => import('./services.component').then((m) => m.ServicesComponent),
      },
      {
        path: 'use-cases',
        loadComponent: () => import('./use-cases.component').then((m) => m.UseCasesComponent),
      },
      {
        path: 'use-cases/:useCaseId',
        loadComponent: () => import('./use-cases.component').then((m) => m.UseCasesComponent),
      },
      // Broken paths under /docs stay in the docs overview instead of
      // falling out to '' (which would redirect unauthenticated users to /login).
      { path: '**', redirectTo: '' },
    ],
  },
];
