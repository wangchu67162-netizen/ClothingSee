import type { ApiErrorShape, User } from '@/types'

const API_BASE = '/api'
const TOKEN_KEY = 'yijian_token'
const USER_KEY = 'yijian_user'
const DEFAULT_TIMEOUT = 30_000

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/* localStorage 在隐私模式/禁用存储时可能抛异常，统一降级为内存态 */
function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function getToken(): string | null {
  try {
    return storage()?.getItem(TOKEN_KEY) ?? null
  } catch {
    return null
  }
}

export function readStoredUser(): User | null {
  try {
    const raw = storage()?.getItem(USER_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<User>
    if (!parsed || typeof parsed !== 'object') return null
    if (typeof parsed.id !== 'number' || typeof parsed.username !== 'string') return null
    return {
      id: parsed.id,
      username: parsed.username,
      nickname: typeof parsed.nickname === 'string' ? parsed.nickname : '',
      created_at: parsed.created_at ?? null,
    }
  } catch {
    return null
  }
}

export function writeSession(token: string, user: User): void {
  try {
    storage()?.setItem(TOKEN_KEY, token)
    storage()?.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    /* 存储不可用时仅保留内存登录态 */
  }
}

export function writeStoredUser(user: User): void {
  try {
    storage()?.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    /* ignore */
  }
}

export function clearSession(): void {
  try {
    storage()?.removeItem(TOKEN_KEY)
    storage()?.removeItem(USER_KEY)
  } catch {
    /* ignore */
  }
}

let lastUnauthorizedAt = 0

/**
 * 401 统一出口：清 token + 通知外壳跳转登录。
 * 1.2s 内只广播一次，避免并发请求造成多个 toast / 多次跳转。
 */
export function notifyUnauthorized(): void {
  const now = Date.now()
  if (now - lastUnauthorizedAt < 1200) return
  lastUnauthorizedAt = now
  clearSession()
  window.dispatchEvent(new CustomEvent('yijian:unauthorized'))
}

function extractDetail(payload: unknown, fallback: string): string {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload.trim() || fallback
  const shape = payload as ApiErrorShape & { message?: unknown; error?: unknown }
  if (typeof shape.detail === 'string') return shape.detail
  if (Array.isArray(shape.detail)) {
    const messages = shape.detail
      .map((item) => (item && typeof item === 'object' ? item.msg : ''))
      .filter((item): item is string => Boolean(item && item.trim()))
    if (messages.length) return messages.join('；')
  }
  if (shape.detail && typeof shape.detail === 'object' && 'message' in shape.detail) {
    const message = (shape.detail as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  if (typeof shape.message === 'string' && shape.message.trim()) return shape.message
  if (typeof shape.error === 'string' && shape.error.trim()) return shape.error
  return fallback
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  rawBody?: BodyInit
  auth?: boolean
  /** 毫秒；<=0 表示不设超时。默认 30s。 */
  timeout?: number
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, rawBody, headers, timeout = DEFAULT_TIMEOUT, signal, ...rest } = options
  const finalHeaders = new Headers(headers)
  const token = auth ? getToken() : null
  if (token) finalHeaders.set('Authorization', `Bearer ${token}`)
  finalHeaders.set('Accept', 'application/json')

  let payload: BodyInit | undefined = rawBody
  if (body !== undefined && rawBody === undefined) {
    finalHeaders.set('Content-Type', 'application/json')
    payload = JSON.stringify(body)
  }

  const controller = new AbortController()
  let timedOut = false
  const abortFromOutside = () => controller.abort()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', abortFromOutside, { once: true })
  }
  const timer =
    timeout > 0
      ? window.setTimeout(() => {
          timedOut = true
          controller.abort()
        }, timeout)
      : 0

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: finalHeaders,
      body: payload,
      signal: controller.signal,
      credentials: rest.credentials ?? 'same-origin',
    })
  } catch (error) {
    if (signal?.aborted) throw error
    if (timedOut) throw new ApiError(0, '请求超时，请稍后重试')
    if (error instanceof ApiError) throw error
    throw new ApiError(0, '网络连接失败，请确认后端服务已启动')
  } finally {
    if (timer) window.clearTimeout(timer)
    signal?.removeEventListener('abort', abortFromOutside)
  }

  if (response.status === 401 && token) {
    // 仅当本次请求确实携带了 token 时才判定为会话失效；
    // 登录失败（auth:false）不应误清已有登录态
    notifyUnauthorized()
  }

  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    if (response.status === 401) detail = '登录状态已失效，请重新登录'
    if (response.status === 403) detail = '没有权限执行该操作'
    if (response.status === 404) detail = '请求的内容不存在'
    if (response.status >= 500) detail = '服务器暂时不可用，请稍后重试'
    try {
      const text = await response.text()
      if (text) {
        try {
          detail = extractDetail(JSON.parse(text), detail)
        } catch {
          if (text.length < 300) detail = text
        }
      }
    } catch {
      /* 响应体不可读时保留状态码文案 */
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204 || response.status === 205) return undefined as T

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('json')) {
    const text = await response.text()
    if (!text) return undefined as T
    try {
      return JSON.parse(text) as T
    } catch {
      throw new ApiError(response.status, '服务器返回了无法解析的数据')
    }
  }
  return (await response.text()) as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  del: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'DELETE' }),
  upload: <T>(path: string, form: FormData, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', rawBody: form }),
  raw: request,
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail
  if (error instanceof DOMException && error.name === 'AbortError') return '请求已取消'
  if (error instanceof TypeError) return '网络连接失败，请确认后端服务已启动'
  if (error instanceof Error) {
    if (/failed to fetch|networkerror|load failed|network request failed/i.test(error.message)) {
      return '网络连接失败，请检查网络或后端服务'
    }
    if (error.message) return error.message
  }
  return '网络异常，请稍后重试'
}
