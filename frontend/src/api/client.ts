import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000',
  timeout: 120000,
})

type RetryConfig = InternalAxiosRequestConfig & { _retry?: boolean }

let refreshPromise: Promise<boolean> | null = null

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

api.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && body.status === 'error') {
      return Promise.reject(body.error || body)
    }
    return resp
  },
  async (err: AxiosError) => {
    const config = err.config as RetryConfig | undefined
    const status = err.response?.status
    const url = config?.url || ''

    if (
      status === 401 &&
      config &&
      !config._retry &&
      !url.includes('/auth/login') &&
      !url.includes('/auth/register') &&
      !url.includes('/auth/refresh')
    ) {
      const auth = useAuthStore()
      config._retry = true
      if (!refreshPromise) {
        refreshPromise = auth.refreshAccessToken().finally(() => {
          refreshPromise = null
        })
      }
      const ok = await refreshPromise
      if (ok && auth.token) {
        config.headers = config.headers || {}
        config.headers.Authorization = `Bearer ${auth.token}`
        return api.request(config)
      }
      await auth.logout()
    }

    const data = err?.response?.data as Record<string, unknown> | undefined
    const detail = (data?.error as Record<string, unknown>) || (data?.detail as Record<string, unknown>)?.error
    if (detail) return Promise.reject(detail)
    if (Array.isArray(data?.detail)) {
      const msg = (data.detail as Array<{ msg?: string }>)
        .map((d) => d.msg || JSON.stringify(d))
        .join('; ')
      return Promise.reject({ code: 'VALIDATION_ERROR', message: msg })
    }
    if (typeof data?.detail === 'string') {
      return Promise.reject({ code: 'HTTP_ERROR', message: data.detail })
    }
    return Promise.reject({
      code: 'HTTP_ERROR',
      message: err?.message || '请求失败',
    })
  },
)

export default api

export function unwrap<T = unknown>(resp: { data: { data: T } }): T {
  return resp.data.data
}
