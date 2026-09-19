import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, from, switchMap } from 'rxjs';

import { environment } from '../../environments/environment';

export type FileType = 'declaracion_renta';

export interface FileRow {
  id: string;
  file_type: FileType | string;
  s3_key: string;
  original_name: string | null;
  size_bytes: number | null;
  content_type: string | null;
  uploaded_at: string;
}

interface UploadUrlResponse {
  upload_url: string;
  key: string;
  content_type: string;
  expires_in: number;
}

interface DownloadUrlResponse {
  download_url: string;
  content_type: string | null;
  original_name: string | null;
  expires_in: number;
}

@Injectable({ providedIn: 'root' })
export class FilesService {
  private http = inject(HttpClient);
  private base = environment.filesApiUrl;

  /**
   * Requests a presigned PUT URL and uploads the browser File to S3 directly.
   * Registration in DB happens asynchronously via the S3 trigger; poll
   * GET /processes/{id} to see the file appear in `files`.
   */
  upload(processId: string, fileType: FileType, file: File): Observable<UploadUrlResponse> {
    const req$ = this.http.post<UploadUrlResponse>(`${this.base}/files/upload-url`, {
      process_id: processId,
      file_type: fileType,
      content_type: file.type || 'application/pdf',
      original_name: file.name,
    });

    return req$.pipe(
      switchMap((r) =>
        from(
          fetch(r.upload_url, {
            method: 'PUT',
            headers: { 'Content-Type': r.content_type },
            body: file,
          }).then((resp) => {
            if (!resp.ok) throw new Error(`S3 upload failed: ${resp.status}`);
            return r;
          }),
        ),
      ),
    );
  }

  downloadUrl(fileId: string): Observable<DownloadUrlResponse> {
    return this.http.get<DownloadUrlResponse>(`${this.base}/files/${fileId}/download-url`);
  }
}
