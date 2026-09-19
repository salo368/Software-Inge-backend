import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink, RouterLinkActive } from '@angular/router';

import { DocsService } from './docs.service';
import { Scenario, Service } from './docs.models';

@Component({
  selector: 'app-docs-services',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './services.component.html',
  styleUrl: './services.component.css',
})
export class ServicesComponent {
  private docs = inject(DocsService);
  private route = inject(ActivatedRoute);

  private data = toSignal(this.docs.parex(), { initialValue: null });
  private params = toSignal(this.route.paramMap);

  services = computed<Service[]>(() => this.data()?.services ?? []);
  actors = computed(() => this.data()?.actors ?? []);
  loading = computed(() => this.data() === null);

  serviceId = computed(() => this.params()?.get('serviceId') ?? null);
  scenarioId = computed(() => this.params()?.get('scenarioId') ?? null);

  selected = computed<Service | null>(() => {
    const id = this.serviceId();
    return id ? this.services().find((s) => s.id === id) ?? null : null;
  });

  selectedScenario = computed<Scenario | null>(() => {
    const s = this.selected();
    const sid = this.scenarioId();
    if (!s || !sid) return null;
    return s.scenarios.find((sc) => sc.id === sid) ?? null;
  });

  actorName(id: string): string {
    return this.actors().find((a) => a.id === id)?.name ?? id;
  }

  useCaseName(id: string): string {
    return this.data()?.useCases.find((u) => u.id === id)?.name ?? '';
  }
}
