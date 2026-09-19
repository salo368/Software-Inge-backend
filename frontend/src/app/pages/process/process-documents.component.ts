import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, inject, signal } from '@angular/core';

import { FileRow, FilesService } from '../../core/files.service';

const POLL_MS = 2000;
const MAX_POLL = 15;

@Component({
  selector: 'app-process-documents',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './process-documents.component.html',
})
export class ProcessDocumentsComponent {
  @Input({ required: true }) processId!: string;
  @Input() files: FileRow[] = [];
  @Output() uploaded = new EventEmitter<void>();

  private api = inject(FilesService);

  uploading = signal(false);
  progressMsg = signal('');
  error = signal<string | null>(null);

  get declaracion(): FileRow | undefined {
    return this.files.find((f) => f.file_type === 'declaracion_renta');
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.uploadFile(file);
    input.value = '';
  }

  uploadFile(file: File): void {
    if (this.uploading()) return;
    this.uploading.set(true);
    this.error.set(null);
    this.progressMsg.set('Subiendo...');
    this.api.upload(this.processId, 'declaracion_renta', file).subscribe({
      next: () => {
        this.progressMsg.set('Registrando...');
        this.pollForFile(0);
      },
      error: () => {
        this.uploading.set(false);
        this.progressMsg.set('');
        this.error.set('No pudimos subir el archivo. Verifica el formato e intenta de nuevo.');
      },
    });
  }

  private pollForFile(attempt: number): void {
    this.uploaded.emit();
    if (this.declaracion) {
      this.uploading.set(false);
      this.progressMsg.set('');
      return;
    }
    if (attempt >= MAX_POLL) {
      this.uploading.set(false);
      this.progressMsg.set('');
      this.error.set('El archivo se subio pero tarda en registrarse. Refresca la pagina en un momento.');
      return;
    }
    setTimeout(() => this.pollForFile(attempt + 1), POLL_MS);
  }

  openFile(): void {
    const f = this.declaracion;
    if (!f) return;
    this.api.downloadUrl(f.id).subscribe({
      next: (r) => window.open(r.download_url, '_blank'),
    });
  }
}
