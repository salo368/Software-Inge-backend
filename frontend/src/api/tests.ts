import { request } from './client'

const TESTS_API = import.meta.env.VITE_TESTS_API_URL

export interface TestResult {
  file: string
  name: string
  escenario: string
  outcome: 'passed' | 'failed' | 'skipped'
  duration: number
  error: string
}

export interface TestRunSummary {
  id: number
  status: 'running' | 'passed' | 'failed' | 'error'
  started_at: string
  finished_at: string | null
  total: number
  passed: number
  failed: number
}

export interface TestRunDetail {
  id: number
  status: TestRunSummary['status']
  started_at: string
  finished_at: string | null
  results: TestResult[]
}

export function startTestRun() {
  return request<{ id: number; status: string }>('/tests/run', { method: 'POST' }, TESTS_API)
}

export function listTestRuns() {
  return request<TestRunSummary[]>('/tests/runs', {}, TESTS_API)
}

export function getTestRun(id: number) {
  return request<TestRunDetail>(`/tests/runs/${id}`, {}, TESTS_API)
}

export interface LoadSample {
  ms: number
  ok: boolean
}

export interface LoadStats {
  done: number
  total: number
  ok: number
  ko: number
  elapsed: number
  rps: number
  avg: number
  min: number
  max: number
  p50: number
  p90: number
  p95: number
  samples: LoadSample[]
}

export interface LoadRunSummary {
  id: number
  status: 'running' | 'passed' | 'failed' | 'error'
  started_at: string
  finished_at: string | null
  scenario: string
  requests: number
  concurrency: number
  done: number
  ok: number
  p95: number | null
}

export interface LoadRunDetail {
  id: number
  status: LoadRunSummary['status']
  started_at: string
  finished_at: string | null
  config: { scenario: string; requests: number; concurrency: number }
  results: Partial<LoadStats>
}

export function startLoadRun(cfg: { scenario: string; requests: number; concurrency: number }) {
  return request<{ id: number; status: string }>(
    '/load-runs',
    { method: 'POST', body: JSON.stringify(cfg) },
    TESTS_API,
  )
}

export function listLoadRuns() {
  return request<LoadRunSummary[]>('/load-runs', {}, TESTS_API)
}

export function getLoadRun(id: number) {
  return request<LoadRunDetail>(`/load-runs/${id}`, {}, TESTS_API)
}
