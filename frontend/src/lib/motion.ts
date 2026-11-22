/** 动效/指针能力检测：统一 reduced-motion 与触屏降级逻辑 */

export function queryMedia(query: string): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  try {
    return window.matchMedia(query)
  } catch {
    return null
  }
}

export function prefersReducedMotion(): boolean {
  return queryMedia('(prefers-reduced-motion: reduce)')?.matches ?? false
}

export function isCoarsePointer(): boolean {
  return queryMedia('(pointer: coarse)')?.matches ?? false
}

/** 订阅媒体查询变化，返回取消订阅函数 */
export function onMediaChange(query: string, handler: (matches: boolean) => void): () => void {
  const media = queryMedia(query)
  if (!media) return () => undefined
  const listener = (event: MediaQueryListEvent) => handler(event.matches)
  if (typeof media.addEventListener === 'function') {
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }
  // 旧版 Safari
  const legacy = media as MediaQueryList & {
    addListener?: (callback: (event: MediaQueryListEvent) => void) => void
    removeListener?: (callback: (event: MediaQueryListEvent) => void) => void
  }
  legacy.addListener?.(listener)
  return () => legacy.removeListener?.(listener)
}
