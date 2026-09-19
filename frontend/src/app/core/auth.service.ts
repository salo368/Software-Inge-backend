import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { environment } from '../../environments/environment';

export interface User {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  user: User;
  token: string;
  expires_at: string;
}

const TOKEN_KEY = 'cdts_token';
const USER_KEY = 'cdts_user';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private base = environment.apiBaseUrl;

  private _token = signal<string | null>(localStorage.getItem(TOKEN_KEY));
  private _user = signal<User | null>(this.readStoredUser());

  readonly user = this._user.asReadonly();
  readonly token = this._token.asReadonly();
  readonly isAuthenticated = computed(() => this._token() !== null);

  register(email: string, password: string, full_name: string): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${this.base}/auth/register`, { email, password, full_name })
      .pipe(tap((r) => this.persist(r)));
  }

  login(email: string, password: string): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>(`${this.base}/auth/login`, { email, password })
      .pipe(tap((r) => this.persist(r)));
  }

  me(): Observable<{ user: User }> {
    return this.http
      .get<{ user: User }>(`${this.base}/auth/me`)
      .pipe(tap((r) => this._user.set(r.user)));
  }

  logout(): Observable<{ revoked: boolean }> {
    return this.http
      .post<{ revoked: boolean }>(`${this.base}/auth/logout`, {})
      .pipe(tap(() => this.clear()));
  }

  clear(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    this._token.set(null);
    this._user.set(null);
  }

  private persist(r: TokenResponse): void {
    localStorage.setItem(TOKEN_KEY, r.token);
    localStorage.setItem(USER_KEY, JSON.stringify(r.user));
    this._token.set(r.token);
    this._user.set(r.user);
  }

  private readStoredUser(): User | null {
    const raw = localStorage.getItem(USER_KEY);
    try {
      return raw ? (JSON.parse(raw) as User) : null;
    } catch {
      return null;
    }
  }
}
