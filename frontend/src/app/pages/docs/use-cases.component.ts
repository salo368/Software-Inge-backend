import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink, RouterLinkActive } from '@angular/router';

import { DocsService } from './docs.service';
import { Flow, FlowType, UseCase } from './docs.models';

@Component({
  selector: 'app-docs-use-cases',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './use-cases.component.html',
  styleUrl: './use-cases.component.css',
})
export class UseCasesComponent {
  private docs = inject(DocsService);
  private route = inject(ActivatedRoute);

  private data = toSignal(this.docs.parex(), { initialValue: null });
  private params = toSignal(this.route.paramMap);
  private fragment = toSignal(this.route.fragment);

  useCases = computed<UseCase[]>(() => this.data()?.useCases ?? []);
  loading = computed(() => this.data() === null);

  useCaseId = computed(() => this.params()?.get('useCaseId') ?? null);

  selected = computed<UseCase | null>(() => {
    const id = this.useCaseId();
    return id ? this.useCases().find((u) => u.id === id) ?? null : null;
  });

  activeFlow = computed(() => this.fragment() ?? null);

  constructor() {
    // Scroll to the selected flow fragment when the selection changes.
    effect(() => {
      const flow = this.activeFlow();
      const uc = this.selected();
      if (flow && uc) {
        queueMicrotask(() => {
          const el = document.getElementById(`flow-${flow}`);
          el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
      }
    });
  }

  flowTypeLabel(type: FlowType): string {
    return {
      basico: 'Basico',
      alternativo: 'Alternativo',
      error: 'Error',
      extensivo: 'Extensivo',
    }[type];
  }

  flowFullName(f: Flow): string {
    if (!f.name) return this.flowTypeLabel(f.type);
    return `${this.flowTypeLabel(f.type)} - ${f.name}`;
  }

  // Splits `composition` into typed tokens so the template can render each
  // token with the right badge style. Example: "P1 -> P2 -> C17-FB -> P3".
  compositionTokens(f: Flow): { type: 'step' | 'flow-ref' | 'arrow' | 'text'; value: string }[] {
    const tokens: { type: 'step' | 'flow-ref' | 'arrow' | 'text'; value: string }[] = [];
    const parts = f.composition.split(/\s+/);
    for (const raw of parts) {
      if (!raw) continue;
      if (raw === '->') tokens.push({ type: 'arrow', value: '→' });
      else if (/^P\d+$/.test(raw)) tokens.push({ type: 'step', value: raw });
      else if (/^C\d+-F[A-Z]\d?$/.test(raw)) tokens.push({ type: 'flow-ref', value: raw });
      else if (/^F[A-Z]\d?$/.test(raw)) tokens.push({ type: 'flow-ref', value: raw });
      else tokens.push({ type: 'text', value: raw });
    }
    return tokens;
  }
}
