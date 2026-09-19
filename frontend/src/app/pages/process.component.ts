import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AnimatedMoneyComponent } from '../components/animated-money.component';
import { BanksService, Bank } from '../core/banks.service';
import { formatCOP } from '../core/format';
import {
  ProcessDetail,
  ProcessesService,
  ProcessStage,
  STAGE_ORDER,
} from '../core/processes.service';
import { ProcessDocumentsComponent } from './process/process-documents.component';
import { ProcessFormComponent } from './process/process-form.component';

interface Step {
  key: ProcessStage;
  label: string;
  icon: string;
}

const STEPS: Step[] = [
  { key: 'form', label: 'Tus datos', icon: 'bi-person-vcard' },
  { key: 'documents', label: 'Documentos', icon: 'bi-file-earmark-arrow-up' },
  { key: 'signature', label: 'Firma', icon: 'bi-vector-pen' },
  { key: 'payment', label: 'Pago', icon: 'bi-credit-card' },
  { key: 'done', label: 'Listo', icon: 'bi-check-circle' },
];

@Component({
  selector: 'app-process',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    AnimatedMoneyComponent,
    ProcessFormComponent,
    ProcessDocumentsComponent,
  ],
  templateUrl: './process.component.html',
})
export class ProcessComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private processesApi = inject(ProcessesService);
  private banksApi = inject(BanksService);

  readonly STEPS = STEPS;
  readonly formatCOP = formatCOP;

  detail = signal<ProcessDetail | null>(null);
  bank = signal<Bank | null>(null);
  loading = signal(true);
  advancing = signal(false);
  error = signal<string | null>(null);

  readonly stage = computed<ProcessStage>(() => this.detail()?.process.stage ?? 'form');
  readonly stageIndex = computed(() => STAGE_ORDER.indexOf(this.stage()));
  readonly interest = computed(() => {
    const p = this.detail()?.process;
    if (!p) return 0;
    const factor = Math.pow(1 + p.rate / 100, p.term_days / 365) - 1;
    return Math.round(p.amount * factor);
  });
  readonly finalAmount = computed(() => {
    const p = this.detail()?.process;
    if (!p) return 0;
    return p.amount + this.interest();
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id')!;
    this.load(id);
  }

  load(id: string): void {
    this.processesApi.get(id).subscribe({
      next: (d) => {
        this.detail.set(d);
        this.loading.set(false);
        this.loadBank(d.process.bank_id);
      },
      error: () => {
        this.loading.set(false);
        this.router.navigate(['/me']);
      },
    });
  }

  private loadBank(bankId: number): void {
    if (this.bank()?.id === bankId) return;
    this.banksApi.listBanks().subscribe({
      next: (r) => this.bank.set(r.banks.find((b) => b.id === bankId) ?? null),
    });
  }

  refresh(): void {
    const d = this.detail();
    if (!d) return;
    this.processesApi.get(d.process.id).subscribe({
      next: (fresh) => this.detail.set(fresh),
    });
  }

  advance(): void {
    const d = this.detail();
    if (!d || this.advancing()) return;
    this.advancing.set(true);
    this.error.set(null);
    this.processesApi.advance(d.process.id).subscribe({
      next: (r) => {
        this.detail.update((cur) => (cur ? { ...cur, process: r.process } : cur));
        this.advancing.set(false);
      },
      error: (err) => {
        this.advancing.set(false);
        this.error.set(this.friendlyError(err?.error?.error));
      },
    });
  }

  onFormSaved(): void {
    // Form was upserted; advance the process out of the `form` stage.
    this.advance();
  }

  private friendlyError(code: string | undefined): string {
    switch (code) {
      case 'form_required':
        return 'Completa el formulario antes de continuar.';
      case 'declaracion_renta_required':
        return 'Debes cargar la declaracion de renta antes de continuar.';
      default:
        return 'No pudimos continuar. Intenta de nuevo en unos segundos.';
    }
  }
}
