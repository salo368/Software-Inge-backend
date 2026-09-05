import { request } from './client'

export interface User {
  id: number
  username: string
  name: string
  created_at?: string
}

export interface LoginResponse {
  token: string
  expires_at: string
  user: User
}

export function register(body: { username: string; name: string; password: string }) {
  return request<User>('/register', { method: 'POST', body: JSON.stringify(body) })
}

export function login(body: { username: string; password: string }) {
  return request<LoginResponse>('/login', { method: 'POST', body: JSON.stringify(body) })
}

export function logout() {
  return request<{ status: string }>('/logout', { method: 'POST' })
}

export function me() {
  return request<User>('/me')
}
