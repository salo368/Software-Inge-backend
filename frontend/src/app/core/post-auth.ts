import { Router } from '@angular/router';

import { PENDING_CDT_KEY, PendingCdtIntent } from '../pages/simulator.component';
import { ProcessesService } from './processes.service';

/**
 * Called after a successful login/register. If the user had a pending CDT
 * intent (clicked "Abrir este CDT" while logged out), materialize the process
 * now and route to the wizard. Otherwise land on the dashboard.
 */
export function completePostAuthRedirect(
  router: Router,
  processesApi: ProcessesService,
): void {
  const raw = localStorage.getItem(PENDING_CDT_KEY);
  if (!raw) {
    router.navigate(['/me']);
    return;
  }
  let intent: PendingCdtIntent;
  try {
    intent = JSON.parse(raw);
  } catch {
    localStorage.removeItem(PENDING_CDT_KEY);
    router.navigate(['/me']);
    return;
  }
  localStorage.removeItem(PENDING_CDT_KEY);
  processesApi.create(intent).subscribe({
    next: (r) => router.navigate(['/process', r.process.id]),
    error: () => router.navigate(['/me']),
  });
}
