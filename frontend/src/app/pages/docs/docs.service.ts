import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, forkJoin, shareReplay } from 'rxjs';

import { ContextoDoc, ParexDoc } from './docs.models';

// Fetches static JSON from /assets/docs/. shareReplay caches the response so
// we don't re-download when the user navigates between /docs subroutes.
@Injectable({ providedIn: 'root' })
export class DocsService {
  private http = inject(HttpClient);

  private parex$?: Observable<ParexDoc>;
  private contexto$?: Observable<ContextoDoc>;

  parex(): Observable<ParexDoc> {
    if (!this.parex$) {
      this.parex$ = this.http
        .get<ParexDoc>('assets/docs/parex.json')
        .pipe(shareReplay({ bufferSize: 1, refCount: false }));
    }
    return this.parex$;
  }

  contexto(): Observable<ContextoDoc> {
    if (!this.contexto$) {
      this.contexto$ = this.http
        .get<ContextoDoc>('assets/docs/contexto.json')
        .pipe(shareReplay({ bufferSize: 1, refCount: false }));
    }
    return this.contexto$;
  }

  all(): Observable<{ parex: ParexDoc; contexto: ContextoDoc }> {
    return forkJoin({ parex: this.parex(), contexto: this.contexto() });
  }
}
