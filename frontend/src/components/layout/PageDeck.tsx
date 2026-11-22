import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface DeckSection {
  id: string
  label: string
  content: ReactNode
  className?: string
}

interface PageDeckProps {
  sections: DeckSection[]
  className?: string
  onIndexChange?: (index: number) => void
}

const clampIndex = (value: number, length: number) => Math.max(0, Math.min(length - 1, value))

/**
 * 整屏翻页（首页 / AI 造型室）
 * - 桌面：滚轮 / 方向键 / PageUp·PageDown / 触控滑动 / 右侧圆点
 * - 内层可滚动区域（[data-deck-scroll] 或 .deck-inner）到达边界后才翻页
 * - <768px 或 prefers-reduced-motion：退化为原生滚动 / 即时跳转
 * - 支持 #hash 深链与 hashchange
 */
export function PageDeck({ sections, className, onIndexChange }: PageDeckProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sectionsRef = useRef(sections)
  const onIndexChangeRef = useRef(onIndexChange)
  const indexRef = useRef(0)
  const lockUntil = useRef(0)
  const reducedRef = useRef(false)
  const hashApplied = useRef(false)
  const wheelAccum = useRef(0)
  const resizeRaf = useRef(0)
  const touchStart = useRef<{ x: number; y: number; time: number; scrollTop: number } | null>(null)

  const [index, setIndex] = useState(0)
  const [announcement, setAnnouncement] = useState('')
  const [mobile, setMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches,
  )

  sectionsRef.current = sections
  onIndexChangeRef.current = onIndexChange

  const sectionTop = useCallback((target: number) => {
    const container = containerRef.current
    if (!container) return 0
    const node = container.children[target] as HTMLElement | undefined
    if (!node) return 0
    return node.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
  }, [])

  const updateIndex = useCallback((next: number) => {
    const list = sectionsRef.current
    if (!list.length) return
    const clamped = clampIndex(next, list.length)
    indexRef.current = clamped
    setIndex(clamped)
    onIndexChangeRef.current?.(clamped)
    const current = list[clamped]
    if (current) {
      const hash = `#${current.id}`
      if (window.location.hash !== hash) {
        try {
          window.history.replaceState(
            window.history.state,
            '',
            `${window.location.pathname}${window.location.search}${hash}`,
          )
        } catch {
          window.location.hash = hash
        }
      }
      setAnnouncement(`第 ${clamped + 1} 屏，共 ${list.length} 屏：${current.label}`)
    }
  }, [])

  const goTo = useCallback(
    (next: number) => {
      const container = containerRef.current
      const list = sectionsRef.current
      if (!container || !list.length) return
      const clamped = clampIndex(next, list.length)
      const instant = reducedRef.current
      // 移动端一屏高度可能远大于视口，平滑滚动到下一屏耗时更久；
      // 适当延长锁，避免滚动途中索引被 onScroll 算回上一屏、圆点来回跳。
      const isMobile = window.matchMedia('(max-width: 767px)').matches
      lockUntil.current = Date.now() + (instant ? 220 : isMobile ? 1100 : 780)
      updateIndex(clamped)
      container.scrollTo({
        top: sectionTop(clamped),
        behavior: instant ? 'auto' : 'smooth',
      })
    },
    [sectionTop, updateIndex],
  )

  const sectionIds = sections.map((section) => section.id).join('|')

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    let alive = true

    const mobileMedia = window.matchMedia('(max-width: 767px)')
    const reduceMedia = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedRef.current = reduceMedia.matches
    setMobile(mobileMedia.matches)

    const isTypingTarget = (target: EventTarget | null) => {
      const element = target instanceof HTMLElement ? target : null
      if (!element) return false
      if (element.isContentEditable) return true
      const tag = element.tagName
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
    }

    const findInnerScroller = (target: EventTarget | null): HTMLElement | null => {
      let node = target instanceof Element ? (target as HTMLElement) : null
      while (node && node !== container) {
        if (node.hasAttribute('data-deck-scroll') || node.classList.contains('deck-inner')) return node
        const style = window.getComputedStyle(node)
        const overflowY = style.overflowY
        if (
          (overflowY === 'auto' || overflowY === 'scroll') &&
          node.scrollHeight > node.clientHeight + 4
        ) {
          return node
        }
        node = node.parentElement
      }
      return null
    }

    const innerCanScroll = (inner: HTMLElement, direction: number) => {
      if (direction > 0) return inner.scrollTop + inner.clientHeight < inner.scrollHeight - 2
      return inner.scrollTop > 2
    }

    const dialogOpen = () =>
      Boolean(document.querySelector('[role="dialog"][aria-modal="true"], #mobile-nav'))

    const onScroll = () => {
      if (Date.now() < lockUntil.current) return
      let next = indexRef.current
      if (mobileMedia.matches) {
        // 移动端每屏高度随内容变化：取当前视口顶部所在的屏（最后一个已到达的屏）
        const top = container.scrollTop + 4
        next = 0
        for (let index = 0; index < sectionsRef.current.length; index += 1) {
          if (sectionTop(index) <= top) next = index
          else break
        }
      } else {
        const height = Math.max(container.clientHeight, 1)
        next = Math.round(container.scrollTop / height)
      }
      next = clampIndex(next, sectionsRef.current.length)
      if (next !== indexRef.current) updateIndex(next)
    }

    const onWheel = (event: WheelEvent) => {
      if (mobileMedia.matches || reduceMedia.matches || dialogOpen()) return
      if (event.ctrlKey || isTypingTarget(event.target)) return
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return

      const multiplier =
        event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? container.clientHeight : 1
      const deltaY = event.deltaY * multiplier
      if (Math.abs(deltaY) < 1) return

      const direction = deltaY > 0 ? 1 : -1
      const inner = findInnerScroller(event.target)
      if (inner && innerCanScroll(inner, direction)) return

      if (Math.sign(deltaY) !== Math.sign(wheelAccum.current)) wheelAccum.current = 0
      wheelAccum.current += deltaY
      event.preventDefault()
      if (Date.now() < lockUntil.current) {
        wheelAccum.current = 0
        return
      }
      if (Math.abs(wheelAccum.current) < 28) return

      const next = indexRef.current + Math.sign(wheelAccum.current)
      wheelAccum.current = 0
      if (next < 0 || next >= sectionsRef.current.length) return
      goTo(next)
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
      if (dialogOpen() || isTypingTarget(event.target)) return
      const inner = findInnerScroller(event.target)
      const forward = event.key === 'ArrowDown' || event.key === 'PageDown'
      const backward = event.key === 'ArrowUp' || event.key === 'PageUp'
      if (forward || backward) {
        const direction = forward ? 1 : -1
        if (inner && innerCanScroll(inner, direction)) return
        event.preventDefault()
        goTo(indexRef.current + direction)
      } else if (event.key === 'Home') {
        event.preventDefault()
        goTo(0)
      } else if (event.key === 'End') {
        event.preventDefault()
        goTo(sectionsRef.current.length - 1)
      }
    }

    const applyHash = (behavior: ScrollBehavior) => {
      const hash = decodeURIComponent(window.location.hash.replace(/^#/, ''))
      if (!hash) return
      const target = sectionsRef.current.findIndex((section) => section.id === hash)
      if (target < 0) return
      lockUntil.current = Date.now() + 220
      updateIndex(target)
      container.scrollTo({ top: sectionTop(target), behavior })
    }

    const onHashChange = () => {
      applyHash(reduceMedia.matches ? 'auto' : 'smooth')
    }

    const onResize = () => {
      if (resizeRaf.current) return
      resizeRaf.current = requestAnimationFrame(() => {
        resizeRaf.current = 0
        if (!alive) return
        container.scrollTo({ top: sectionTop(indexRef.current), behavior: 'auto' })
      })
    }

    const onMobileChange = (event: MediaQueryListEvent) => {
      setMobile(event.matches)
      window.requestAnimationFrame(() => {
        if (!alive) return
        container.scrollTo({ top: sectionTop(indexRef.current), behavior: 'auto' })
      })
    }

    const onReduceChange = () => {
      reducedRef.current = reduceMedia.matches
    }

    const onTouchStart = (event: TouchEvent) => {
      const touch = event.touches[0]
      if (!touch) return
      touchStart.current = {
        x: touch.clientX,
        y: touch.clientY,
        time: performance.now(),
        scrollTop: container.scrollTop,
      }
    }

    const onTouchEnd = (event: TouchEvent) => {
      const start = touchStart.current
      touchStart.current = null
      const touch = event.changedTouches[0]
      if (!start || !touch) return
      // 移动端完全交给原生 scroll-snap；仅处理平板/触屏桌面上未被原生滚动的滑动
      if (mobileMedia.matches || reduceMedia.matches) return
      const dy = touch.clientY - start.y
      const dx = touch.clientX - start.x
      if (Math.abs(dy) < 56 || Math.abs(dy) <= Math.abs(dx) * 1.3) return
      if (performance.now() - start.time > 900) return
      if (Math.abs(container.scrollTop - start.scrollTop) > 12) return
      const direction = dy < 0 ? 1 : -1
      const inner = findInnerScroller(event.target)
      if (inner && innerCanScroll(inner, direction)) return
      const next = indexRef.current + direction
      if (next < 0 || next >= sectionsRef.current.length) return
      goTo(next)
    }

    container.addEventListener('scroll', onScroll, { passive: true })
    container.addEventListener('wheel', onWheel, { passive: false })
    container.addEventListener('touchstart', onTouchStart, { passive: true })
    container.addEventListener('touchend', onTouchEnd, { passive: true })
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('hashchange', onHashChange)
    window.addEventListener('resize', onResize)
    mobileMedia.addEventListener('change', onMobileChange)
    reduceMedia.addEventListener('change', onReduceChange)

    const initialRaf = requestAnimationFrame(() => {
      if (!alive) return
      if (!hashApplied.current) {
        hashApplied.current = true
        const hash = decodeURIComponent(window.location.hash.replace(/^#/, ''))
        const target = sectionsRef.current.findIndex((section) => section.id === hash)
        if (target > 0) {
          lockUntil.current = Date.now() + 220
          updateIndex(target)
          container.scrollTo({ top: sectionTop(target), behavior: 'auto' })
        }
      }
    })

    return () => {
      alive = false
      cancelAnimationFrame(initialRaf)
      if (resizeRaf.current) cancelAnimationFrame(resizeRaf.current)
      container.removeEventListener('scroll', onScroll)
      container.removeEventListener('wheel', onWheel)
      container.removeEventListener('touchstart', onTouchStart)
      container.removeEventListener('touchend', onTouchEnd)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('hashchange', onHashChange)
      window.removeEventListener('resize', onResize)
      mobileMedia.removeEventListener('change', onMobileChange)
      reduceMedia.removeEventListener('change', onReduceChange)
    }
    // sections 内容每次渲染都会变化，仅按 id 列表重建监听，避免重复应用 hash
  }, [goTo, sectionIds, sectionTop, updateIndex])

  if (!sections.length) {
    return (
      <div
        className={cn('flex min-h-[70vh] items-center justify-center px-6 text-center', className)}
        role="status"
      >
        <div>
          <p className="display text-2xl text-ivory/80">这一页还没有内容</p>
          <p className="mt-2 text-sm text-ivory/55">请稍后刷新页面再试。</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('relative h-[100dvh] w-full', className)}>
      <p className="sr-only">
        这是一个整屏翻页页面。使用上下方向键、PageUp / PageDown、滚轮或右侧圆点切换屏幕；按 Home
        返回第一屏，按 End 前往最后一屏。
      </p>
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>

      <div ref={containerRef} className="deck-scroll h-full">
        {sections.map((section, sectionIndex) => (
          <section
            key={section.id}
            id={section.id}
            aria-label={`${section.label}（第 ${sectionIndex + 1} 屏，共 ${sections.length} 屏）`}
            aria-current={sectionIndex === index ? 'true' : undefined}
            className={cn(
              // 移动端留出底部圆点导航的高度，避免最后一段内容被遮挡
              'deck-section flex w-full flex-col overflow-hidden px-5 pb-28 pt-24 md:px-10 md:pb-10 md:pt-28',
              section.className,
            )}
          >
            {section.content}
          </section>
        ))}
      </div>

      <nav
        className="fixed right-3 top-1/2 z-[85] hidden -translate-y-1/2 flex-col items-center gap-3 md:flex"
        aria-label="页面章节导航"
      >
        {sections.map((section, sectionIndex) => (
          <button
            key={section.id}
            type="button"
            onClick={() => goTo(sectionIndex)}
            className="group relative flex items-center rounded-full p-2"
            aria-label={`前往第 ${sectionIndex + 1} 屏：${section.label}`}
            aria-current={sectionIndex === index ? 'step' : undefined}
          >
            {/* 悬浮提示做成实底胶囊，避免它压到页面内容时与正文混在一起。 */}
            <span
              aria-hidden="true"
              className="pointer-events-none absolute right-full top-1/2 mr-2 -translate-y-1/2 whitespace-nowrap rounded-full border border-white/10 bg-ink-950/90 px-2.5 py-1 text-[10px] tracking-[0.16em] text-ivory/70 opacity-0 shadow-lg backdrop-blur-md transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100"
            >
              {section.label}
            </span>
            <span
              className={cn(
                'block h-1.5 w-1.5 rounded-full border transition-all duration-500',
                sectionIndex === index
                  ? 'scale-125 border-champagne bg-champagne shadow-[0_0_16px_rgba(216,190,147,.65)]'
                  : 'border-ivory/30 bg-transparent',
              )}
              aria-hidden="true"
            />
          </button>
        ))}
      </nav>

      {mobile ? (
        <div
          role="navigation"
          aria-label="页面章节导航（移动端）"
          className="deck-mobile-nav fixed inset-x-0 z-[85] flex items-center justify-center gap-2 border-t border-white/10 bg-ink-950/95 px-3 py-2.5 shadow-[0_-10px_30px_rgba(0,0,0,0.45)] backdrop-blur-md"
        >
          {sections.map((section, sectionIndex) => (
            <button
              key={section.id}
              type="button"
              onClick={() => goTo(sectionIndex)}
              className="flex h-8 w-8 items-center justify-center rounded-full"
              aria-label={`前往第 ${sectionIndex + 1} 屏：${section.label}`}
              aria-current={sectionIndex === index ? 'step' : undefined}
            >
              <span
                className={cn(
                  'block h-1 rounded-full transition-all',
                  sectionIndex === index ? 'w-5 bg-champagne' : 'w-1.5 bg-ivory/40',
                )}
                aria-hidden="true"
              />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default PageDeck
