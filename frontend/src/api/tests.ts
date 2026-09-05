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
