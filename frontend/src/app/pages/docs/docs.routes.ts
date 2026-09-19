import { Routes } from '@angular/router';

// Rutas hijas de /docs, todas lazy. Servicios y casos de uso re-usan el mismo
// componente cuando solo cambian los params (default RouteReuseStrategy de Angular).
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
      // Rutas rotas dentro de /docs se quedan en el overview de docs; no salen a
      // '' (que es protegida y redirige a /login sin sesion).
      { path: '**', redirectTo: '' },
    ],
  },
];
