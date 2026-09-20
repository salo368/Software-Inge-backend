import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, from, map, switchMap, throwError } from 'rxjs';

import { environment } from '../../environments/environment';

export type SignatureStage = 'review' | 'identity' | 'drawing' | 'otp' | 'signed';
export type EvidenceType = 'cedula_front' | 'cedula_back' | 'face' | 'signature';

export const SIGNATURE_STAGE_ORDER: SignatureStage[] = [
  'review',
  'identity',
  'drawing',
  'otp',
  'signed',
];

export interface SignatureCeremony {
  token: string;
  process_id: string;
  stage: SignatureStage;
  page: number;
  x: number;
  y: number;
  email_masked: string;
  uploads: Record<EvidenceType, boolean>;
  doc_hash: string | null;
  signed_at: string | null;
  pdf_url: string;
  signed_pdf_url?: string;
}

export interface CreateSignatureResponse {
  signature: SignatureCeremony;
  sign_url: string;
  pdf_url?: string;
  emailed?: boolean;
  reused?: boolean;
}

interface UploadUrlResponse {
  upload_url: string;
  key: string;
  upload_headers: Record<string, string>;
  stage: SignatureStage;
}

export interface OtpResponse {
  status: 'sent' | 'undelivered';
  stage: SignatureStage;
  /** Only present outside production when the mailbox could not be reached. */
  dev_otp?: string;
}

export interface ConfirmResponse {
  status: 'signed';
  doc_hash: string;
  signed_pdf_url: string;
  process_id: string;
  process_stage: string;
}

@Injectable({ providedIn: 'root' })
export class SignaturesService {
  private http = inject(HttpClient);
  private base = environment.signaturesApiUrl;

  create(processId: string): Observable<CreateSignatureResponse> {
    return this.http.post<CreateSignatureResponse>(`${this.base}/signatures`, {
      process_id: processId,
    });
  }

  get(token: string): Observable<SignatureCeremony> {
    return this.http.get<SignatureCeremony>(`${this.base}/signatures/${token}`);
  }

  /** Presigns, PUTs straight to S3, then asks the backend to validate it. */
  uploadEvidence(
    token: string,
    type: EvidenceType,
    blob: Blob,
    contentType: string,
  ): Observable<UploadUrlResponse> {
    return this.http
      .post<UploadUrlResponse>(`${this.base}/signatures/${token}/upload-url`, {
        type,
        content_type: contentType,
      })
      .pipe(
        switchMap((r) =>
          from(
            fetch(r.upload_url, { method: 'PUT', headers: r.upload_headers, body: blob }),
          ).pipe(
            switchMap((resp) =>
              resp.ok ? [r] : throwError(() => new Error(`S3 respondio ${resp.status}`)),
            ),
          ),
        ),
      );
  }

  validate(token: string, type: EvidenceType): Observable<boolean> {
    return this.http
      .post<{ valid: boolean }>(`${this.base}/signatures/${token}/validate`, { type })
      .pipe(map((r) => r.valid));
  }

  requestOtp(token: string): Observable<OtpResponse> {
    return this.http.post<OtpResponse>(`${this.base}/signatures/${token}/otp`, {});
  }

  confirm(token: string, otp: string): Observable<ConfirmResponse> {
    return this.http.post<ConfirmResponse>(`${this.base}/signatures/${token}/confirm`, { otp });
  }
}
