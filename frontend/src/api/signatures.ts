import { request } from './client'

const SIGN_API = import.meta.env.VITE_SIGN_API_URL

export interface SignatureProcess {
  id: number
  sign_url: string
  email: string
}

export function createSignature(body: { cdt_id: number; email: string }) {
  return request<SignatureProcess>('/signatures', {
    method: 'POST',
    body: JSON.stringify(body),
  }, SIGN_API)
}
