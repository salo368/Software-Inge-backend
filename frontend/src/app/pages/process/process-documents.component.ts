import { CommonModule } from '@angular/common';
import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  inject,
  signal,
} from '@angular/core';

import { FileRow, FilesService } from '../../core/files.service';

const POLL_MS = 2000;
const MAX_POLL = 15;

@Component({
  selector: 'app-process-documents',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './process-documents.component.html',
})
export class ProcessDocumentsComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) processId!: string;
  @Input() files: FileRow[] = [];
  @Output() uploaded = new EventEmitter<void>();

  private api = inject(FilesService);
  private pollTimer: number | null = null;
  private attempts = 0;

  uploading = signal(false);
  progressMsg = signal('');
  error = signal<string | null>(null);

  get declaracion(): FileRow | undefined {
    return this.files.find((f) => f.file_type === 'declaracion_renta');
  }

  // The parent refreshes asynchronously after each `uploaded` emit, so the
  // registered row shows up here as a new `files` array rather than inline.
  ngOnChanges(): void {
    if (this.uploading() && this.declaracion) this.stopPolling('');
  }

  ngOnDestroy(): void {
    this.clearTimer();
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
        this.progressMsg.set('Registrando el documento...');
        this.startPolling();
      },
      error: () => {
        this.uploading.set(false);
        this.progressMsg.set('');
        this.error.set('No pudimos subir el archivo. Verifica el formato e intenta de nuevo.');
      },
    });
  }

  private startPolling(): void {
    this.attempts = 0;
    this.clearTimer();
    this.uploaded.emit();
    this.pollTimer = window.setInterval(() => {
      this.attempts += 1;
      if (this.attempts >= MAX_POLL) {
        this.stopPolling(
          'El archivo se subio pero tarda en registrarse. Recarga la pagina en unos segundos.',
        );
        return;
      }
      this.uploaded.emit();
    }, POLL_MS);
  }

  private stopPolling(errorMsg: string): void {
    this.clearTimer();
    this.uploading.set(false);
    this.progressMsg.set('');
    if (errorMsg) this.error.set(errorMsg);
  }

  private clearTimer(): void {
    if (this.pollTimer !== null) {
      window.clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  openFile(): void {
    const f = this.declaracion;
    if (!f) return;
    this.api.downloadUrl(f.id).subscribe({
      next: (r) => window.open(r.download_url, '_blank'),
    });
  }
}
