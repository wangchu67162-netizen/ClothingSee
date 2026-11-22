import type { SseEnvelope } from '@/types'
import { ApiError, getToken, notifyUnauthorized } from './api'

export interface SseOptions {
  signal?: AbortSignal
  headers?: Record<string, string>
}

function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const text = await response.text()
    if (!text) return fallback
    try {
      const data = JSON.parse(text) as { detail?: unknown; message?: unknown }
      if (typeof data.detail === 'string') return data.detail
      if (Array.isArray(data.detail)) {
        const messages = data.detail
          .map((item) => (item && typeof item === 'object' ? (item as { msg?: string }).msg : ''))
          .filter(Boolean)
        if (messages.length) return messages.join('；')
      }
      if (typeof data.message === 'string') return data.message
    } catch {
      return text.length <= 300 ? text : fallback
    }
  } catch {
    /* 响应体不可读 */
  }
  return fallback
}

/**
 * POST + fetch/ReadableStream 解析 SSE。
 * - 自动携带 Bearer；401 清 token 并广播 yijian:unauthorized
 * - 支持跨 chunk、CRLF / LF / CR、注释心跳（: ping）、多行 data
 * - 非法 JSON 以字符串形式交给调用方，不中断流
 */
export async function postSSE<T = unknown>(
  path: string,
  body: FormData | Record<string, unknown>,
  onEvent: (event: SseEnvelope<T>) => void,
  options: SseOptions = {},
): Promise<void> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'text/event-stream')
  headers.set('Cache-Control', 'no-cache')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let payload: BodyInit
  if (body instanceof FormData) {
    payload = body
  } else {
    headers.set('Content-Type', 'application/json')
    payload = JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method: 'POST',
      headers,
      body: payload,
      signal: options.signal,
      credentials: 'same-origin',
    })
  } catch (error) {
    if (isAbortError(error, options.signal)) return
    if (error instanceof ApiError) throw error
    throw new ApiError(0, '流式连接失败，请确认后端服务已启动')
  }

  if (response.status === 401) {
    if (token) notifyUnauthorized()
    throw new ApiError(401, '登录状态已失效，请重新登录')
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response, `流式请求失败（${response.status}）`)
    throw new ApiError(response.status, detail)
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType && !contentType.includes('text/event-stream')) {
    const detail = await readErrorDetail(response, '服务端未返回流式响应，请稍后重试')
    throw new ApiError(response.ok ? 502 : response.status, detail)
  }

  if (!response.body) throw new ApiError(0, '当前浏览器不支持流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let eventName = 'message'
  let eventId: string | undefined
  let dataLines: string[] = []

  const dispatch = () => {
    const name = eventName || 'message'
    const id = eventId
    eventName = 'message'
    if (!dataLines.length) return
    const raw = dataLines.join('\n')
    dataLines = []
    let data: unknown = raw
    if (raw) {
      try {
        data = JSON.parse(raw)
      } catch {
        /* 保留原始字符串，事件仍可展示 */
      }
    }
    try {
      onEvent({ event: name, data: data as T, id })
    } catch (error) {
      // 单个事件的渲染错误不应中断后续流
      console.error('[SSE] 事件处理异常', error)
    }
  }

  const processLine = (line: string) => {
    if (line === '') {
      dispatch()
      return
    }
    if (line.startsWith(':')) return // 心跳 / 注释
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') {
      eventName = value
    } else if (field === 'data') {
      dataLines.push(value)
    } else if (field === 'id') {
      if (!value.includes('\u0000')) eventId = value
    }
    // retry 等字段对一次性 POST 流无意义，忽略
  }

  /** 从 buffer 头部取出完整行；flush 时把残留内容也当作最后一行 */
  const drain = (flush = false) => {
    if (buffer.charCodeAt(0) === 0xfeff) buffer = buffer.slice(1)
    while (buffer.length) {
      const lf = buffer.indexOf('\n')
      const cr = buffer.indexOf('\r')
      let index = -1
      if (lf === -1) index = cr
      else if (cr === -1) index = lf
      else index = Math.min(lf, cr)
      if (index === -1) break
      // 末尾单独的 \r 可能是下一个 chunk 的 \r\n 前半个字节
      if (index === buffer.length - 1 && buffer[index] === '\r' && !flush) break
      const advance = buffer[index] === '\r' && buffer[index + 1] === '\n' ? 2 : 1
      const line = buffer.slice(0, index)
      buffer = buffer.slice(index + advance)
      processLine(line)
    }
    if (flush) {
      if (buffer.length) {
        processLine(buffer)
        buffer = ''
      }
      dispatch()
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      drain()
    }
    buffer += decoder.decode()
    drain(true)
  } catch (error) {
    if (isAbortError(error, options.signal)) {
      try {
        await reader.cancel()
      } catch {
        /* ignore */
      }
      return
    }
    try {
      await reader.cancel()
    } catch {
      /* ignore */
    }
    throw error
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* ignore */
    }
  }
}

export default postSSE
