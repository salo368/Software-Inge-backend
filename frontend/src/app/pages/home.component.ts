import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { AnimatedMoneyComponent } from '../components/animated-money.component';
import { AuthService } from '../core/auth.service';
import { BanksService, Bank } from '../core/banks.service';
import { formatCOP } from '../core/format';
import { ProcessRow, ProcessStage, ProcessesService } from '../core/processes.service';

const STAGE_LABEL: Record<ProcessStage, string> = {
  form: 'Diligenciando datos',
  documents: 'Cargando documentos',
  signature: 'Firma pendiente',
  payment: 'Pago pendiente',
  done: 'CDT activo',
};

const STAGE_CLASS: Record<ProcessStage, string> = {
  form: 'text-bg-warning',
  documents: 'text-bg-warning',
  signature: 'text-bg-info',
  payment: 'text-bg-info',
  done: 'text-bg-success',
};

interface Row {
  proc: ProcessRow;
  bank: Bank | undefined;
}

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule, RouterLink, AnimatedMoneyComponent],
  templateUrl: './home.component.html',
})
export class HomeComponent implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);
  private processesApi = inject(ProcessesService);
  private banksApi = inject(BanksService);

  readonly formatCOP = formatCOP;
  readonly stageLabel = STAGE_LABEL;
  readonly stageClass = STAGE_CLASS;
  readonly user = this.auth.user;

  loading = signal(true);
  logoutBusy = signal(false);
  processes = signal<ProcessRow[]>([]);
  banks = signal<Bank[]>([]);

  readonly rows = computed<Row[]>(() =>
    this.processes().map((p) => ({
      proc: p,
      bank: this.banks().find((b) => b.id === p.bank_id),
    })),
  );

  ngOnInit(): void {
    this.auth.me().subscribe({ error: () => {} });

    this.banksApi.listBanks().subscribe({ next: (r) => this.banks.set(r.banks) });

    this.processesApi.listMine().subscribe({
      next: (r) => {
        this.processes.set(r.processes);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  interest(p: ProcessRow): number {
    const factor = Math.pow(1 + p.rate / 100, p.term_days / 365) - 1;
    return Math.round(p.amount * factor);
  }

  logout(): void {
    if (this.logoutBusy()) return;
    this.logoutBusy.set(true);
    this.auth.logout().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => {
        this.auth.clear();
        this.router.navigate(['/login']);
      },
    });
  }
}
