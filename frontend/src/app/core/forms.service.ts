import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export type DocumentType = 'CC' | 'CE' | 'PASAPORTE' | 'TI';

export interface UserForm {
  full_name: string;
  birth_date: string; // YYYY-MM-DD
  document_type: DocumentType;
  document_number: string;
  phone: string;
  address: string;
  city: string;
  occupation: string;
  economic_activity: string;
  monthly_income: number;
  monthly_expenses: number;
  total_assets: number;
  total_liabilities: number;
  source_of_funds: string;
  is_peps: boolean;
  updated_at?: string;
}

@Injectable({ providedIn: 'root' })
export class FormsService {
  private http = inject(HttpClient);
  private base = environment.formsApiUrl;

  getMine(): Observable<{ form: UserForm | null }> {
    return this.http.get<{ form: UserForm | null }>(`${this.base}/forms/me`);
  }

  upsertMine(payload: UserForm): Observable<{ form: UserForm }> {
    return this.http.put<{ form: UserForm }>(`${this.base}/forms/me`, payload);
  }
}
