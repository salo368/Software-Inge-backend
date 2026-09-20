import { CommonModule } from '@angular/common';
import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  ViewChild,
  signal,
} from '@angular/core';

export type CameraMode = 'document' | 'face';

/** ISO ID-1 (85.6 x 54 mm), the aspect ratio of a Colombian cedula. */
const CARD_RATIO = 1.586;

@Component({
  selector: 'app-camera-capture',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './camera-capture.component.html',
})
export class CameraCaptureComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) mode!: CameraMode;
  @Input() busy = false;
  @Output() captured = new EventEmitter<Blob>();

  @ViewChild('video') videoRef?: ElementRef<HTMLVideoElement>;
  @ViewChild('wrap') wrapRef?: ElementRef<HTMLDivElement>;
  @ViewChild('guide') guideRef?: ElementRef<HTMLDivElement>;

  camError = signal(false);
  shotUrl = signal('');

  private stream: MediaStream | null = null;
  private shot: Blob | null = null;

  ngOnChanges(): void {
    // Switching between document and face flips the camera, so restart.
    this.retake();
  }

  ngOnDestroy(): void {
    this.stopStream();
    this.discard();
  }

  async start(): Promise<void> {
    this.stopStream();
    this.camError.set(false);
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: this.mode === 'face' ? 'user' : 'environment',
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      // The view may not be attached yet on the first tick after a mode change.
      setTimeout(() => {
        if (this.videoRef) this.videoRef.nativeElement.srcObject = this.stream;
      });
    } catch {
      this.camError.set(true);
    }
  }

  private stopStream(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }

  private discard(): void {
    if (this.shotUrl()) URL.revokeObjectURL(this.shotUrl());
    this.shot = null;
    this.shotUrl.set('');
  }

  retake(): void {
    this.discard();
    void this.start();
  }

  /** Public so the parent can force a fresh shot after a rejected photo. */
  reset(): void {
    this.retake();
  }

  capture(): void {
    const v = this.videoRef?.nativeElement;
    const w = this.wrapRef?.nativeElement;
    const g = this.guideRef?.nativeElement;
    if (!v || !w || !g || !v.videoWidth) return;

    // Map the on-screen guide back to video pixels; the video is object-fit:
    // cover, so part of it is cropped on one axis.
    const wr = w.getBoundingClientRect();
    const gr = g.getBoundingClientRect();
    const scale = Math.max(wr.width / v.videoWidth, wr.height / v.videoHeight);
    const offX = (v.videoWidth * scale - wr.width) / 2;
    const offY = (v.videoHeight * scale - wr.height) / 2;
    let sx = (gr.left - wr.left + offX) / scale;
    const sy = (gr.top - wr.top + offY) / scale;
    const sw = gr.width / scale;
    const sh = gr.height / scale;

    const mirrored = this.mode === 'face';
    if (mirrored) sx = v.videoWidth - sx - sw;

    const outW = this.mode === 'document' ? 1280 : 900;
    const outH = this.mode === 'document' ? Math.round(1280 / CARD_RATIO) : 1200;
    const canvas = document.createElement('canvas');
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext('2d')!;
    if (mirrored) {
      ctx.translate(outW, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(v, sx, sy, sw, sh, 0, 0, outW, outH);
    canvas.toBlob(
      (b) => {
        if (!b) return;
        this.discard();
        this.shot = b;
        this.shotUrl.set(URL.createObjectURL(b));
        this.stopStream();
      },
      'image/jpeg',
      0.92,
    );
  }

  confirmShot(): void {
    if (this.shot && !this.busy) this.captured.emit(this.shot);
  }
}
