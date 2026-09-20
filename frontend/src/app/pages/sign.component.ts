import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import {
  EvidenceType,
  SignatureCeremony,
  SignatureStage,
  SignaturesService,
} from '../core/signatures.service';
import { CameraCaptureComponent, CameraMode } from './sign/camera-capture.component';
import { PdfPreviewComponent } from './sign/pdf-preview.component';
import { SignaturePadComponent } from './sign/signature-pad.component';

type Step = 'review' | 'identity' | 'drawing' | 'otp' | 'done';

interface StepDef {
  key: Step;
  label: string;
  icon: string;
}

const STEPS: StepDef[] = [
  { key: 'review', label: 'Revision', icon: 'bi-file-earmark-text' },
  { key: 'identity', label: 'Identidad', icon: 'bi-person-badge' },
  { key: 'drawing', label: 'Firma', icon: 'bi-vector-pen' },
  { key: 'otp', label: 'Codigo', icon: 'bi-envelope-check' },
];

interface DocDef {
  type: EvidenceType;
  label: string;
  short: string;
  hint: string;
  icon: string;
  mode: CameraMode;
}

const DOCS: DocDef[] = [
  {
    type: 'cedula_front',
    label: 'Cedula - cara frontal',
    short: 'Cedula frontal',
    hint: 'Centra el frente de tu cedula dentro del recuadro',
    icon: 'bi-person-vcard',
    mode: 'document',
  },
  {
    type: 'cedula_back',
    label: 'Cedula - cara posterior',
    short: 'Cedula posterior',
    hint: 'Ahora la cara posterior, que se lea el codigo',
    icon: 'bi-person-vcard-fill',
    mode: 'document',
  },
  {
    type: 'face',
    label: 'Foto de tu rostro',
    short: 'Tu rostro',
    hint: 'Ubica tu rostro dentro del ovalo, con buena luz',
    icon: 'bi-emoji-smile',
    mode: 'face',
  },
];

// Only ever used to decide whether the server is ahead of the local step.
const STEP_RANK: Record<Step, number> = { review: 0, identity: 1, drawing: 2, otp: 3, done: 4 };
const STAGE_RANK: Record<SignatureStage, number> = {
  review: 0,
  identity: 1,
  drawing: 2,
  otp: 3,
  signed: 4,
};

@Component({
  selector: 'app-sign',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    CameraCaptureComponent,
    PdfPreviewComponent,
    SignaturePadComponent,
  ],
  templateUrl: './sign.component.html',
})
export class SignComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private api = inject(SignaturesService);

  @ViewChild(CameraCaptureComponent) camera?: CameraCaptureComponent;

  readonly STEPS = STEPS;
  readonly DOCS = DOCS;

  token = '';
  ceremony = signal<SignatureCeremony | null>(null);
  notFound = signal(false);
  step = signal<Step>('review');
  error = signal('');
  busy = signal(false);
  uploadBusy = signal(false);

  docDone = signal<Record<EvidenceType, boolean>>({
    cedula_front: false,
    cedula_back: false,
    face: false,
    signature: false,
  });
  currentDoc = signal<EvidenceType | ''>('');

  signatureBlob: Blob | null = null;
  otp = '';
  otpSent = signal(false);
  devOtp = signal('');
  signedPdfUrl = signal('');
  docHash = signal('');

  readonly stepIndex = computed(() => STEPS.findIndex((s) => s.key === this.step()));
  readonly activeDoc = computed(() => DOCS.find((d) => d.type === this.currentDoc()) ?? null);
  readonly allDocsDone = computed(() => {
    const d = this.docDone();
    return d.cedula_front && d.cedula_back && d.face;
  });

  private poll: number | null = null;

  ngOnInit(): void {
    // Angular reuses the component across tokens, so read the param stream
    // rather than the snapshot.
    this.route.paramMap.subscribe((params) => {
      this.token = params.get('token')!;
      this.load();
    });
  }

  private load(): void {
    this.notFound.set(false);
    this.ceremony.set(null);
    this.api.get(this.token).subscribe({
      next: (c) => {
        this.apply(c);
        this.step.set(c.stage === 'signed' ? 'done' : c.stage);
        if (c.stage === 'otp') this.otpSent.set(false);
        if (c.signed_pdf_url) this.signedPdfUrl.set(c.signed_pdf_url);
        // Evidence can also be captured on another device; only move forward.
        if (this.poll === null) this.poll = window.setInterval(() => this.sync(), 4000);
      },
      error: () => this.notFound.set(true),
    });
  }

  ngOnDestroy(): void {
    if (this.poll !== null) window.clearInterval(this.poll);
  }

  private apply(c: SignatureCeremony): void {
    this.ceremony.set(c);
    this.docDone.set({ ...c.uploads });
    this.currentDoc.set(this.nextPendingDoc());
  }

  private nextPendingDoc(): EvidenceType | '' {
    const done = this.docDone();
    return DOCS.find((d) => !done[d.type])?.type ?? '';
  }

  private sync(): void {
    if (this.notFound() || this.busy() || this.uploadBusy() || this.step() === 'done') return;
    this.api.get(this.token).subscribe({
      next: (c) => {
        this.docDone.set({ ...c.uploads });
        if (this.step() === 'identity' && !this.currentDoc()) {
          this.currentDoc.set(this.nextPendingDoc());
        }
        if (STAGE_RANK[c.stage] > STEP_RANK[this.step()]) {
          if (c.stage === 'signed') {
            this.step.set('done');
            if (c.signed_pdf_url) this.signedPdfUrl.set(c.signed_pdf_url);
          } else {
            this.step.set(c.stage);
            if (c.stage === 'otp') this.otpSent.set(true);
          }
        }
      },
      error: () => {
        /* transient; the next tick retries */
      },
    });
  }

  goToIdentity(): void {
    this.step.set('identity');
    this.currentDoc.set(this.nextPendingDoc());
  }

  pickDoc(type: EvidenceType): void {
    if (this.uploadBusy()) return;
    this.currentDoc.set(type);
  }

  onCaptured(blob: Blob): void {
    const type = this.currentDoc();
    if (!type || this.uploadBusy()) return;
    this.uploadBusy.set(true);
    this.error.set('');

    this.api.uploadEvidence(this.token, type, blob, 'image/jpeg').subscribe({
      next: () => {
        this.api.validate(this.token, type).subscribe({
          next: (valid) => {
            this.uploadBusy.set(false);
            if (!valid) {
              this.docDone.update((d) => ({ ...d, [type]: false }));
              this.error.set(
                'No pudimos validar la foto. Tomala de nuevo con buena luz y sin reflejos.',
              );
              this.camera?.reset();
              return;
            }
            this.docDone.update((d) => ({ ...d, [type]: true }));
            this.currentDoc.set(this.nextPendingDoc());
            this.camera?.reset();
          },
          error: () => {
            this.uploadBusy.set(false);
            this.error.set('No pudimos validar la foto. Intenta de nuevo.');
          },
        });
      },
      error: () => {
        this.uploadBusy.set(false);
        this.error.set('No pudimos subir la foto. Revisa tu conexion.');
      },
    });
  }

  submitSignature(): void {
    if (!this.signatureBlob || this.busy()) return;
    this.busy.set(true);
    this.error.set('');

    this.api
      .uploadEvidence(this.token, 'signature', this.signatureBlob, 'image/png')
      .subscribe({
        next: () => this.sendOtp(),
        error: () => {
          this.busy.set(false);
          this.error.set('No pudimos guardar tu firma. Intenta de nuevo.');
        },
      });
  }

  sendOtp(): void {
    this.busy.set(true);
    this.error.set('');
    this.api.requestOtp(this.token).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.otpSent.set(true);
        this.devOtp.set(r.dev_otp ?? '');
        this.step.set('otp');
      },
      error: () => {
        this.busy.set(false);
        this.error.set('No pudimos enviar el codigo. Intenta de nuevo.');
      },
    });
  }

  confirm(): void {
    if (this.otp.length !== 6 || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.api.confirm(this.token, this.otp).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.signedPdfUrl.set(r.signed_pdf_url);
        this.docHash.set(r.doc_hash);
        this.step.set('done');
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(this.friendlyError(err?.error?.error));
      },
    });
  }

  backToProcess(): void {
    const c = this.ceremony();
    void this.router.navigate(c ? ['/process', c.process_id] : ['/me']);
  }

  private friendlyError(code: string | undefined): string {
    if (code?.startsWith('invalid_otp')) {
      const left = code.split(':')[1];
      return `Codigo incorrecto. Intentos restantes: ${left ?? 0}.`;
    }
    switch (code) {
      case 'otp_expired':
        return 'El codigo vencio. Pide uno nuevo.';
      case 'too_many_attempts':
        return 'Demasiados intentos fallidos. Pide un codigo nuevo.';
      case 'otp_not_requested':
        return 'Primero pide el codigo a tu correo.';
      default:
        return 'No pudimos confirmar la firma. Intenta de nuevo.';
    }
  }
}
