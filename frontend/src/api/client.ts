const API_URL = import.meta.env.VITE_API_URL
const TOKEN_KEY = 'cdts_token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setStoredToken(t: string | null): void {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export async function request<T>(path: string, opts: RequestInit = {}, base: string = API_URL): Promise<T> {
  const headers = new Headers(opts.headers)
  headers.set('Content-Type', 'application/json')

  const token = getStoredToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${base}${path}`, { ...opts, headers })
  const isJson = res.headers.get('content-type')?.includes('json')
  const data = isJson ? await res.json() : null

  if (!res.ok) {
    const code = data?.error || 'http_error'
    const message = data?.detail || code
    throw new ApiError(res.status, code, message)
  }

  return data as T
}
