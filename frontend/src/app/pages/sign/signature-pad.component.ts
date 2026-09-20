import { CommonModule } from '@angular/common';
import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Output,
  ViewChild,
} from '@angular/core';

@Component({
  selector: 'app-signature-pad',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div>
      <canvas
        #pad
        width="900"
        height="300"
        class="sig-pad"
        (pointerdown)="down($event)"
        (pointermove)="move($event)"
        (pointerup)="up()"
        (pointercancel)="up()"
      ></canvas>
      <div class="d-flex justify-content-between align-items-center mt-2">
        <span class="small text-body-secondary">Dibuja tu firma con el dedo o el mouse</span>
        <button type="button" class="btn btn-outline-secondary btn-sm" (click)="clear()">
          <i class="bi bi-eraser me-1"></i>Limpiar
        </button>
      </div>
    </div>
  `,
})
export class SignaturePadComponent implements AfterViewInit {
  @ViewChild('pad') padRef!: ElementRef<HTMLCanvasElement>;
  @Output() changed = new EventEmitter<Blob | null>();

  private ctx!: CanvasRenderingContext2D;
  private drawing = false;
  private hasInk = false;

  ngAfterViewInit(): void {
    this.ctx = this.padRef.nativeElement.getContext('2d')!;
    this.clear();
  }

  private pos(e: PointerEvent): { x: number; y: number } {
    const c = this.padRef.nativeElement;
    const r = c.getBoundingClientRect();
    return {
      x: (e.clientX - r.left) * (c.width / r.width),
      y: (e.clientY - r.top) * (c.height / r.height),
    };
  }

  down(e: PointerEvent): void {
    this.drawing = true;
    this.padRef.nativeElement.setPointerCapture(e.pointerId);
    const p = this.pos(e);
    this.ctx.beginPath();
    this.ctx.moveTo(p.x, p.y);
  }

  move(e: PointerEvent): void {
    if (!this.drawing) return;
    const p = this.pos(e);
    this.ctx.lineTo(p.x, p.y);
    this.ctx.stroke();
    this.hasInk = true;
  }

  up(): void {
    if (!this.drawing) return;
    this.drawing = false;
    if (this.hasInk) {
      this.padRef.nativeElement.toBlob((b) => this.changed.emit(b), 'image/png');
    }
  }

  clear(): void {
    const c = this.padRef.nativeElement;
    // A white fill rather than clearRect: the PNG is stamped onto the PDF and
    // a transparent background renders as black in some viewers.
    this.ctx.fillStyle = '#ffffff';
    this.ctx.fillRect(0, 0, c.width, c.height);
    this.ctx.strokeStyle = '#17143a';
    this.ctx.lineWidth = 3.5;
    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';
    this.hasInk = false;
    this.changed.emit(null);
  }
}
