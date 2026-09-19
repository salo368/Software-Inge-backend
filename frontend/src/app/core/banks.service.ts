import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export interface Bank {
  id: number;
  code: string;
  name: string;
  logo_url: string;
  description: string;
  tier: string;
  rating_by: string;
  min_amount: number;
  highlights: string[];
}

export interface BanksResponse {
  banks: Bank[];
}

/** Un resultado de simulacion para un banco. */
export interface SimulationRow {
  bank: Bank;
  rate: number;
  interest: number;
  final: number;
}

export interface SimulationResponse {
  amount: number;
  term_days: number;
  results: SimulationRow[];
}

@Injectable({ providedIn: 'root' })
export class BanksService {
  private http = inject(HttpClient);
  private base = environment.banksApiUrl;

  listBanks(): Observable<BanksResponse> {
    return this.http.get<BanksResponse>(`${this.base}/banks`);
  }

  simulate(amount: number, term_days: number): Observable<SimulationResponse> {
    return this.http.post<SimulationResponse>(`${this.base}/banks/simulate`, { amount, term_days });
  }
}
