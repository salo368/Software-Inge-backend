import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  Component,
  ElementRef,
  Input,
  ViewChild,
  signal,
} from '@angular/core';
import * as pdfjs from 'pdfjs-dist';

// Copied into assets by the `pdfjs-worker` glob in angular.json.
pdfjs.GlobalWorkerOptions.workerSrc = 'assets/pdf.worker.min.mjs';

@Component({
  selector: 'app-pdf-preview',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div #wrap class="pdf-wrap">
      <div *ngIf="!ready() && !failed()" class="text-center py-5">
        <div class="spinner-border text-primary" role="status"></div>
      </div>
      <div *ngIf="failed()" class="text-center py-5 text-body-secondary small">
        No pudimos cargar la vista previa.
        <a [href]="pdfUrl" target="_blank" class="d-block mt-2">Abrir el documento en otra pestana</a>
      </div>
      <canvas #canvas [hidden]="!ready()"></canvas>
      <div
        *ngIf="ready()"
        class="sig-box"
        [style.left.%]="x"
        [style.top.%]="y"
        [style.width.%]="28"
      >
        <i class="bi bi-vector-pen"></i> Tu firma ira aqui
      </div>
    </div>
  `,
})
export class PdfPreviewComponent implements AfterViewInit {
  @Input({ required: true }) pdfUrl!: string;
  @Input() page = 1;
  @Input() x = 0;
  @Input() y = 0;

  @ViewChild('wrap') wrapRef!: ElementRef<HTMLDivElement>;
  @ViewChild('canvas') canvasRef!: ElementRef<HTMLCanvasElement>;

  ready = signal(false);
  failed = signal(false);

  async ngAfterViewInit(): Promise<void> {
    try {
      const doc = await pdfjs.getDocument(this.pdfUrl).promise;
      const page = await doc.getPage(this.page);
      const containerW = this.wrapRef.nativeElement.clientWidth;
      const base = page.getViewport({ scale: 1 });
      const scale = (containerW / base.width) * (window.devicePixelRatio || 1);
      const viewport = page.getViewport({ scale });
      const canvas = this.canvasRef.nativeElement;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
      this.ready.set(true);
    } catch {
      this.failed.set(true);
    }
  }
}
