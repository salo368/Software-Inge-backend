import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';

import { DocsService } from './docs.service';

@Component({
  selector: 'app-docs-overview',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './overview.component.html',
  styleUrl: './overview.component.css',
})
export class OverviewComponent {
  private docs = inject(DocsService);

  private data = toSignal(this.docs.contexto(), { initialValue: null });

  identity = computed(() => this.data()?.identity);
  canvas = computed(() => this.data()?.canvas ?? []);
  actorRoles = computed(() => this.data()?.actorRoles ?? []);
  capabilities = computed(() => this.data()?.capabilities ?? []);
  products = computed(() => this.data()?.products ?? []);
  loading = computed(() => this.data() === null);
}
