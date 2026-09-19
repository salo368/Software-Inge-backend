import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { FileRow } from './files.service';
import { UserForm } from './forms.service';

export type ProcessStage = 'form' | 'documents' | 'signature' | 'payment' | 'done';

export const STAGE_ORDER: ProcessStage[] = ['form', 'documents', 'signature', 'payment', 'done'];

export interface ProcessRow {
  id: string;
  bank_id: number;
  amount: number;
  term_days: number;
  rate: number;
  stage: ProcessStage;
  form_snapshot: UserForm | null;
  signed_at: string | null;
  paid_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ProcessDetail {
  process: ProcessRow;
  files: FileRow[];
}

@Injectable({ providedIn: 'root' })
export class ProcessesService {
  private http = inject(HttpClient);
  private base = environment.processesApiUrl;

  create(payload: {
    bank_id: number;
    amount: number;
    term_days: number;
    rate: number;
  }): Observable<{ process: ProcessRow }> {
    return this.http.post<{ process: ProcessRow }>(`${this.base}/processes`, payload);
  }

  listMine(): Observable<{ processes: ProcessRow[] }> {
    return this.http.get<{ processes: ProcessRow[] }>(`${this.base}/processes`);
  }

  get(id: string): Observable<ProcessDetail> {
    return this.http.get<ProcessDetail>(`${this.base}/processes/${id}`);
  }

  advance(id: string): Observable<{ process: ProcessRow }> {
    return this.http.post<{ process: ProcessRow }>(`${this.base}/processes/${id}/advance`, {});
  }
}
