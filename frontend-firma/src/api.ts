const API = import.meta.env.VITE_SIGN_API_URL

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...opts.headers },
  })
  const isJson = res.headers.get('content-type')?.includes('json')
  const data = isJson ? await res.json() : null
  if (!res.ok) {
    const code = data?.error || 'http_error'
    throw new ApiError(res.status, code, data?.detail || code)
  }
  return data as T
}

export type UploadType = 'cedula_front' | 'cedula_back' | 'face' | 'signature'

export interface SignProcess {
  stage: 'revision' | 'documentos' | 'dibujo' | 'otp' | 'firmado'
  cdt_id: number
  pdf_url: string
  page: number
  x: number
  y: number
  email_masked: string
  return_url: string
  uploads: Record<UploadType, boolean>
}

export function getProcess(token: string) {
  return req<SignProcess>(`/signatures/${token}`)
}

export function getUploadUrl(token: string, type: UploadType, contentType: string) {
  return req<{ upload_url: string; key: string; stage: string }>(
    `/signatures/${token}/uploads`,
    { method: 'POST', body: JSON.stringify({ type, content_type: contentType }) },
  )
}

export async function putFile(url: string, blob: Blob, contentType: string): Promise<void> {
  const res = await fetch(url, { method: 'PUT', headers: { 'Content-Type': contentType }, body: blob })
  if (!res.ok) throw new ApiError(res.status, 'upload_failed', 'No se pudo subir el archivo')
}

export function validatePhoto(token: string, type: UploadType) {
  return req<{ valid: boolean }>(
    `/signatures/${token}/validate`,
    { method: 'POST', body: JSON.stringify({ type }) },
  )
}

export function requestOtp(token: string) {
  return req<{ status: string }>(`/signatures/${token}/otp`, { method: 'POST' })
}

export function confirmOtp(token: string, otp: string) {
  return req<{ status: string; return_url: string; signed_pdf_url: string }>(
    `/signatures/${token}/confirm`,
    { method: 'POST', body: JSON.stringify({ otp }) },
  )
}
