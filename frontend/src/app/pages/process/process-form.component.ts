import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, EventEmitter, OnInit, Output, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { FormsService, UserForm } from '../../core/forms.service';

const DOCUMENT_TYPES = ['CC', 'CE', 'PASAPORTE', 'TI'] as const;

@Component({
  selector: 'app-process-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './process-form.component.html',
})
export class ProcessFormComponent implements OnInit {
  @Output() saved = new EventEmitter<void>();

  private fb = inject(FormBuilder);
  private api = inject(FormsService);

  readonly DOCUMENT_TYPES = DOCUMENT_TYPES;

  loading = signal(true);
  saving = signal(false);
  error = signal<string | null>(null);
  prefilled = signal(false);

  form = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, Validators.minLength(3)]],
    birth_date: ['', [Validators.required]],
    document_type: ['CC', [Validators.required]],
    document_number: ['', [Validators.required, Validators.minLength(4)]],
    phone: ['', [Validators.required, Validators.minLength(7)]],
    address: ['', [Validators.required, Validators.minLength(4)]],
    city: ['', [Validators.required]],
    occupation: ['', [Validators.required]],
    economic_activity: ['', [Validators.required]],
    monthly_income: [0, [Validators.required, Validators.min(0)]],
    monthly_expenses: [0, [Validators.required, Validators.min(0)]],
    total_assets: [0, [Validators.required, Validators.min(0)]],
    total_liabilities: [0, [Validators.required, Validators.min(0)]],
    source_of_funds: ['', [Validators.required, Validators.minLength(3)]],
    is_peps: [false],
  });

  ngOnInit(): void {
    this.api.getMine().subscribe({
      next: (r) => {
        if (r.form) {
          this.form.patchValue(r.form as Partial<UserForm>);
          this.prefilled.set(true);
        }
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  submit(): void {
    if (this.form.invalid || this.saving()) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    const value = this.form.getRawValue() as UserForm;
    this.api.upsertMine(value).subscribe({
      next: () => {
        this.saving.set(false);
        this.saved.emit();
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.error.set(err.error?.error ?? 'No pudimos guardar. Revisa los campos.');
      },
    });
  }
}
