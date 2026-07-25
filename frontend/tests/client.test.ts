/**
 * api client 错误解包逻辑测试。
 *
 * client.ts 在 import 时向 axios 实例注册拦截器；这里 mock 整个 axios 模块，
 * 捕获响应拦截器后直接用构造的错误对象驱动它，验证解包语义。
 */
import { describe, expect, it, vi } from 'vitest'

type ResOk = (resp: { data: unknown }) => unknown
type ResBad = (err: unknown) => Promise<unknown>

const captured: { resOk?: ResOk; resBad?: ResBad } = {}

vi.mock('axios', () => ({
  default: {
    create: () => ({
      interceptors: {
        request: { use: vi.fn() },
        response: {
          use: (ok: ResOk, bad: ResBad) => {
            captured.resOk = ok
            captured.resBad = bad
          },
        },
      },
    }),
  },
}))

const { default: api, unwrap } = await import('@/api/client')

function httpError(status: number, data: unknown, message = 'Request failed') {
  return {
    response: { status, data },
    config: { url: '/some/endpoint', headers: {} },
    message,
  }
}

describe('api client 响应解包', () => {
  it('业务错误体（status=error）直接拒绝为 error 对象', async () => {
    const body = { status: 'error', error: { code: 'BIZ', message: '业务失败' } }
    await expect(captured.resOk!({ data: body })).rejects.toEqual({
      code: 'BIZ',
      message: '业务失败',
    })
  })

  it('正常响应原样透传', () => {
    const resp = { data: { status: 'ok', data: { id: 1 } } }
    expect(captured.resOk!(resp)).toBe(resp)
  })

  it('FastAPI 校验错误数组拼接为 VALIDATION_ERROR', async () => {
    const err = httpError(422, {
      detail: [{ msg: '邮箱格式不正确' }, { msg: '密码至少 8 位' }],
    })
    await expect(captured.resBad!(err)).rejects.toEqual({
      code: 'VALIDATION_ERROR',
      message: '邮箱格式不正确; 密码至少 8 位',
    })
  })

  it('字符串 detail 解包为 HTTP_ERROR', async () => {
    const err = httpError(404, { detail: '资源不存在' })
    await expect(captured.resBad!(err)).rejects.toEqual({
      code: 'HTTP_ERROR',
      message: '资源不存在',
    })
  })

  it('嵌套 error 对象原样抛出', async () => {
    const err = httpError(500, { error: { code: 'INTERNAL', message: '服务器错误' } })
    await expect(captured.resBad!(err)).rejects.toEqual({
      code: 'INTERNAL',
      message: '服务器错误',
    })
  })

  it('无响应体时回退到 axios message', async () => {
    await expect(captured.resBad!({ message: 'Network Error' })).rejects.toEqual({
      code: 'HTTP_ERROR',
      message: 'Network Error',
    })
  })

  it('unwrap 取出 data.data 载荷', () => {
    expect(unwrap({ data: { data: { token: 't' } } })).toEqual({ token: 't' })
  })

  it('axios 实例已创建且拦截器已注册', () => {
    expect(api).toBeTruthy()
    expect(captured.resOk).toBeTypeOf('function')
    expect(captured.resBad).toBeTypeOf('function')
  })
})
