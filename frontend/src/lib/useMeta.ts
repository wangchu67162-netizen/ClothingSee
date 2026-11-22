import { useCallback, useEffect, useRef, useState } from 'react'
import { api, apiErrorMessage } from './api'
import type { Meta } from '@/types'

const META_TTL = 120_000

let cached: Meta | null = null
let cachedAt = 0
let inflight: Promise<Meta> | null = null

function fetchMeta(): Promise<Meta> {
  if (inflight) return inflight
  const task = api.get<Meta>('/meta', { auth: false }).then((value) => {
    cached = value
    cachedAt = Date.now()
    return value
  })
  inflight = task
  task
    .finally(() => {
      if (inflight === task) inflight = null
    })
    .catch(() => undefined)
  return task
}

/** 运行模式（Mock / Qwen）缓存钩子，避免每次导航重复请求 */
export function useMeta() {
  const [meta, setMeta] = useState<Meta | null>(cached)
  const [loading, setLoading] = useState(!cached)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(true)
  const seq = useRef(0)

  const load = useCallback(async () => {
    const current = ++seq.current
    if (!cached) setLoading(true)
    try {
      const value = await fetchMeta()
      if (current !== seq.current || !mounted.current) return
      setMeta(value)
      setError(null)
    } catch (reason) {
      if (current !== seq.current || !mounted.current) return
      setError(apiErrorMessage(reason))
    } finally {
      if (current === seq.current && mounted.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    if (!cached) {
      void load()
    } else if (Date.now() - cachedAt > META_TTL) {
      void load()
    } else {
      setMeta(cached)
      setLoading(false)
    }
    return () => {
      mounted.current = false
      seq.current += 1
    }
  }, [load])

  const refresh = useCallback(() => {
    cachedAt = 0
    return load()
  }, [load])

  return { meta, loading, error, refresh }
}

export default useMeta
