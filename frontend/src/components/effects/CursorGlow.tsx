import { useEffect, useRef } from 'react'
import { onMediaChange, queryMedia } from '@/lib/motion'

/** 跟随鼠标的柔光层：仅精细指针 + 非 reduced-motion + 桌面宽度启用 */
export function CursorGlow() {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const coarseMedia = queryMedia('(pointer: coarse)')
    const reduceMedia = queryMedia('(prefers-reduced-motion: reduce)')

    let raf = 0
    let targetX = -400
    let targetY = -400
    let currentX = -400
    let currentY = -400
    let hasPointer = false

    const enabled = () =>
      !(coarseMedia?.matches ?? false) &&
      !(reduceMedia?.matches ?? false) &&
      window.innerWidth >= 768

    const apply = () => {
      node.style.transform = `translate3d(${currentX - 220}px, ${currentY - 220}px, 0)`
    }

    const tick = () => {
      raf = 0
      currentX += (targetX - currentX) * 0.12
      currentY += (targetY - currentY) * 0.12
      apply()
      if (Math.abs(targetX - currentX) > 0.4 || Math.abs(targetY - currentY) > 0.4) {
        raf = requestAnimationFrame(tick)
      }
    }

    const stop = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
    }

    const onMove = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse' || !enabled()) return
      targetX = event.clientX
      targetY = event.clientY
      hasPointer = true
      node.style.opacity = ''
      if (!raf) raf = requestAnimationFrame(tick)
    }

    const onLeave = () => {
      hasPointer = false
      stop()
      node.style.opacity = '0'
    }

    const onEnter = () => {
      if (enabled()) node.style.opacity = ''
    }

    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        stop()
      } else if (hasPointer && enabled()) {
        if (!raf) raf = requestAnimationFrame(tick)
      }
    }

    const onResize = () => {
      if (!enabled()) {
        stop()
        node.style.opacity = '0'
      } else if (hasPointer) {
        node.style.opacity = ''
      }
    }

    const offCoarse = onMediaChange('(pointer: coarse)', onResize)
    const offReduced = onMediaChange('(prefers-reduced-motion: reduce)', onResize)

    if (!enabled()) node.style.opacity = '0'
    apply()
    window.addEventListener('pointermove', onMove, { passive: true })
    document.addEventListener('pointerleave', onLeave)
    document.addEventListener('pointerenter', onEnter)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('resize', onResize)

    return () => {
      stop()
      offCoarse()
      offReduced()
      window.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerleave', onLeave)
      document.removeEventListener('pointerenter', onEnter)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', onResize)
    }
  }, [])

  return (
    <div
      ref={ref}
      aria-hidden="true"
      className="cursor-glow pointer-events-none fixed left-0 top-0 z-[1] hidden h-[440px] w-[440px] select-none rounded-full opacity-70 blur-2xl md:block"
      style={{
        willChange: 'transform',
        background:
          'radial-gradient(circle, rgba(216,190,147,0.10) 0%, rgba(255,107,61,0.045) 35%, rgba(7,7,11,0) 68%)',
      }}
    />
  )
}

export default CursorGlow
