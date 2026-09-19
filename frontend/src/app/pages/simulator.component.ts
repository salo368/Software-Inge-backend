import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AnimatedMoneyComponent } from '../components/animated-money.component';
import { AuthService } from '../core/auth.service';
import { BanksService, SimulationRow } from '../core/banks.service';
import { formatCOP, tierCss } from '../core/format';

interface TermOption {
  key: number;
  label: string;
}

const TERMS: TermOption[] = [
  { key: 90, label: '3 meses' },
  { key: 180, label: '6 meses' },
  { key: 360, label: '12 meses' },
  { key: 540, label: '18 meses' },
  { key: 720, label: '24 meses' },
];

const TIER_RANK: Record<string, number> = { AAA: 5, 'AA+': 4, AA: 3, 'A+': 2, A: 1 };
const TIER_LABEL: Record<string, string> = {
  AAA: 'Solidez maxima',
  'AA+': 'Solidez muy alta',
  AA: 'Solidez alta',
  'A+': 'Solidez media',
  A: 'Solidez estandar',
};

@Component({
  selector: 'app-simulator',
  standalone: true,
  imports: [CommonModule, FormsModule, AnimatedMoneyComponent],
  templateUrl: './simulator.component.html',
})
export class SimulatorComponent implements OnInit {
  private banksApi = inject(BanksService);
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly TERMS = TERMS;
  readonly formatCOP = formatCOP;
  readonly tierCss = tierCss;
  readonly tierLabel = TIER_LABEL;

  amount = signal<number>(5_000_000);
  term = signal<number>(360);
  sortBy = signal<'yield' | 'safety'>('yield');
  showResults = signal(false);

  loading = signal(false);
  error = signal<string | null>(null);
  results = signal<SimulationRow[]>([]);

  totalBanks = signal(0);

  readonly selectedTermLabel = computed(
    () => TERMS.find((t) => t.key === this.term())?.label ?? '',
  );
  readonly isValid = computed(() => (this.amount() || 0) > 0);
  readonly marketMin = computed(() => {
    const r = this.results();
    return r.length ? Math.min(...r.map((x) => x.rate)) : 0;
  });
  readonly marketMax = computed(() => {
    const r = this.results();
    return r.length ? Math.max(...r.map((x) => x.rate)) : 0;
  });
  readonly sortedResults = computed(() => {
    const rows = [...this.results()];
    if (this.sortBy() === 'safety') {
      rows.sort(
        (a, b) =>
          (TIER_RANK[b.bank.tier] ?? 0) - (TIER_RANK[a.bank.tier] ?? 0) || b.rate - a.rate,
      );
    } else {
      rows.sort((a, b) => b.rate - a.rate);
    }
    return rows;
  });

  ngOnInit(): void {
    // Pre-cargar la lista de bancos solo para el contador del hero.
    this.banksApi.listBanks().subscribe({
      next: (r) => this.totalBanks.set(r.banks.length),
    });
  }

  onSimulate(): void {
    if (!this.isValid() || this.loading()) return;
    this.loading.set(true);
    this.error.set(null);
    this.banksApi.simulate(this.amount(), this.term()).subscribe({
      next: (r) => {
        this.results.set(r.results);
        this.showResults.set(true);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err?.error?.error || 'No se pudo simular. Intenta de nuevo.');
      },
    });
  }

  changeTerm(t: number): void {
    if (this.term() === t) return;
    this.term.set(t);
    // Si ya hay resultados a la vista, re-simular con el nuevo plazo.
    if (this.showResults()) this.onSimulate();
  }

  openCdt(row: SimulationRow): void {
    if (!this.auth.isAuthenticated()) {
      this.router.navigate(['/register']);
      return;
    }
    // Placeholder: la funcionalidad de apertura de CDT sera futura.
    // Por ahora navegamos a /me como landing autenticado.
    this.router.navigate(['/me']);
  }
}
