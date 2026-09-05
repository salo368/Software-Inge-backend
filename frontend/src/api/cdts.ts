import { request } from './client'
import type { StageKey } from '../data/stages'

const CDTS_API = import.meta.env.VITE_CDTS_API_URL

export interface Cdt {
  id: number
  user_id: number
  stage: StageKey
  rate: string
  amount: string
  term: number
  signature_url: string | null
  opened_at: string
  created_at: string
  updated_at: string
}

export function createCdt(body: { amount: number; term: number; rate: number }) {
  return request<Cdt>('/cdts', { method: 'POST', body: JSON.stringify(body) }, CDTS_API)
}

export function listCdts() {
  return request<Cdt[]>('/cdts', {}, CDTS_API)
}

export function getCdt(id: number | string) {
  return request<Cdt>(`/cdts/${id}`, {}, CDTS_API)
}

export function advanceCdt(id: number | string) {
  return request<Cdt>(`/cdts/${id}/advance`, { method: 'POST' }, CDTS_API)
}
