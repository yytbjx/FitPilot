import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api, { unwrap } from '@/api/client'

const REFRESH_KEY = 'fitpilot_refresh'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('fitpilot_token'))
  const refreshToken = ref<string | null>(localStorage.getItem(REFRESH_KEY))
  const email = ref<string | null>(localStorage.getItem('fitpilot_email'))
  const userId = ref<number | null>(
    localStorage.getItem('fitpilot_uid') ? Number(localStorage.getItem('fitpilot_uid')) : null,
  )
  const role = ref<string | null>(localStorage.getItem('fitpilot_role'))

  const isLoggedIn = computed(() => !!token.value)

  function persist() {
    if (token.value) localStorage.setItem('fitpilot_token', token.value)
    else localStorage.removeItem('fitpilot_token')
    if (refreshToken.value) localStorage.setItem(REFRESH_KEY, refreshToken.value)
    else localStorage.removeItem(REFRESH_KEY)
    if (email.value) localStorage.setItem('fitpilot_email', email.value)
    if (userId.value != null) localStorage.setItem('fitpilot_uid', String(userId.value))
    if (role.value) localStorage.setItem('fitpilot_role', role.value)
    else localStorage.removeItem('fitpilot_role')
  }

  function applyTokens(data: {
    access_token: string
    refresh_token?: string
    email?: string
    user_id?: number
    role?: string
  }) {
    token.value = data.access_token
    if (data.refresh_token) refreshToken.value = data.refresh_token
    if (data.email) email.value = data.email
    if (data.user_id != null) userId.value = data.user_id
    if (data.role) role.value = data.role
    persist()
  }

  async function login(addr: string, password: string) {
    const data = unwrap(await api.post('/auth/login', { email: addr, password }))
    applyTokens(data)
  }

  async function register(addr: string, password: string) {
    const data = unwrap(await api.post('/auth/register', { email: addr, password }))
    applyTokens(data)
  }

  async function refreshAccessToken(): Promise<boolean> {
    if (!refreshToken.value) return false
    try {
      const data = unwrap(
        await api.post('/auth/refresh', { refresh_token: refreshToken.value }),
      )
      applyTokens(data)
      return true
    } catch {
      return false
    }
  }

  async function logout() {
    if (refreshToken.value && token.value) {
      try {
        await api.post('/auth/logout', { refresh_token: refreshToken.value })
      } catch {
        /* 忽略登出失败 */
      }
    }
    token.value = null
    refreshToken.value = null
    email.value = null
    userId.value = null
    role.value = null
    localStorage.removeItem('fitpilot_token')
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem('fitpilot_email')
    localStorage.removeItem('fitpilot_uid')
    localStorage.removeItem('fitpilot_role')
  }

  return {
    token,
    refreshToken,
    email,
    userId,
    role,
    isLoggedIn,
    login,
    register,
    refreshAccessToken,
    logout,
    applyTokens,
  }
})
