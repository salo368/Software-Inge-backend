import { ref } from 'vue'
import { getStoredToken, setStoredToken } from '../api/client'
import { me as fetchMe, logout as apiLogout, type User } from '../api/access'

const token = ref<string | null>(getStoredToken())
const user = ref<User | null>(null)

async function loadUser(): Promise<void> {
  if (!token.value) return
  try {
    user.value = await fetchMe()
  } catch {
    setToken(null)
  }
}

function setToken(t: string | null): void {
  token.value = t
  setStoredToken(t)
  if (!t) user.value = null
}

async function logout(): Promise<void> {
  try { await apiLogout() } catch { /* ignore */ }
  setToken(null)
}

// hidrata user en el primer import (si hay token guardado)
if (token.value) loadUser()

export function useAuth() {
  return { token, user, setToken, loadUser, logout }
}
