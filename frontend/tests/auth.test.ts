/**
 * auth store 登录流程测试：mock api client + 内存版 localStorage。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }))

vi.mock('@/api/client', () => ({
  default: { post: postMock },
  unwrap: (resp: { data: { data: unknown } }) => resp.data.data,
}))

// node 环境无 DOM：用内存 Map 模拟 localStorage
const mem = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (k: string) => (mem.has(k) ? mem.get(k)! : null),
  setItem: (k: string, v: string) => void mem.set(k, String(v)),
  removeItem: (k: string) => void mem.delete(k),
  clear: () => mem.clear(),
})

const { useAuthStore } = await import('@/stores/auth')

const LOGIN_PAYLOAD = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  email: 'u@fit.dev',
  user_id: 7,
  role: 'user',
}

describe('auth store', () => {
  beforeEach(() => {
    mem.clear()
    postMock.mockReset()
    setActivePinia(createPinia())
  })

  it('login 成功：保存 token 并持久化到 localStorage', async () => {
    postMock.mockResolvedValueOnce({ data: { data: LOGIN_PAYLOAD } })
    const auth = useAuthStore()

    await auth.login('u@fit.dev', 'secret-pw')

    expect(postMock).toHaveBeenCalledWith('/auth/login', {
      email: 'u@fit.dev',
      password: 'secret-pw',
    })
    expect(auth.token).toBe('access-1')
    expect(auth.refreshToken).toBe('refresh-1')
    expect(auth.email).toBe('u@fit.dev')
    expect(auth.userId).toBe(7)
    expect(auth.isLoggedIn).toBe(true)
    expect(mem.get('fitpilot_token')).toBe('access-1')
    expect(mem.get('fitpilot_refresh')).toBe('refresh-1')
  })

  it('login 失败：错误向上传播且不写入任何凭证', async () => {
    postMock.mockRejectedValueOnce({ code: 'HTTP_ERROR', message: '邮箱或密码错误' })
    const auth = useAuthStore()

    await expect(auth.login('u@fit.dev', 'bad-pw')).rejects.toEqual({
      code: 'HTTP_ERROR',
      message: '邮箱或密码错误',
    })
    expect(auth.token).toBeNull()
    expect(auth.isLoggedIn).toBe(false)
    expect(mem.has('fitpilot_token')).toBe(false)
  })

  it('refreshAccessToken：无 refresh token 时直接返回 false，不发请求', async () => {
    const auth = useAuthStore()
    expect(await auth.refreshAccessToken()).toBe(false)
    expect(postMock).not.toHaveBeenCalled()
  })

  it('logout：清空状态与本地存储', async () => {
    postMock.mockResolvedValueOnce({ data: { data: LOGIN_PAYLOAD } })
    const auth = useAuthStore()
    await auth.login('u@fit.dev', 'secret-pw')
    expect(auth.isLoggedIn).toBe(true)

    postMock.mockResolvedValueOnce({ data: { data: {} } })
    await auth.logout()

    expect(auth.token).toBeNull()
    expect(auth.refreshToken).toBeNull()
    expect(auth.email).toBeNull()
    expect(auth.isLoggedIn).toBe(false)
    expect(mem.has('fitpilot_token')).toBe(false)
    expect(mem.has('fitpilot_refresh')).toBe(false)
  })
})
