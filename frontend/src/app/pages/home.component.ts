import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { environment } from '../../environments/environment';
import { AuthService } from '../core/auth.service';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './home.component.html',
  styleUrl: './home.component.css',
})
export class HomeComponent implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly stage = environment.stage;
  readonly user = this.auth.user;

  loading = signal(false);
  error = signal<string | null>(null);

  ngOnInit(): void {
    this.auth.me().subscribe({
      error: () => {
        // Interceptor ya redirige a /login en 401.
      },
    });
  }

  logout(): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.auth.logout().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => {
        // Interceptor clears + redirects on 401. For other errors we still bail out locally.
        this.auth.clear();
        this.router.navigate(['/login']);
      },
    });
  }
}
