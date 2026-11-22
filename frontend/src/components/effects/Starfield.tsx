import { useEffect, useRef } from 'react'
import { cn } from '@/lib/cn'
import { onMediaChange, queryMedia } from '@/lib/motion'

interface Star {
  x: number
  y: number
  radius: number
  alpha: number
  twinkle: number
  phase: number
  depth: number
  warm: boolean
}

interface Meteor {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  maxLife: number
}

const DPR_CAP = 2
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

export function Starfield({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d', { alpha: true })
    if (!context) return

    const reduceMedia = queryMedia('(prefers-reduced-motion: reduce)')
    const coarseMedia = queryMedia('(pointer: coarse)')
    let width = 0
    let height = 0
    let dpr = 1
    let stars: Star[] = []
    let meteor: Meteor | null = null
    let nextMeteorAt = 0
    let raf = 0
    let running = document.visibilityState !== 'hidden'
    let lastTs = 0
    let scrollY = window.scrollY
    let resizeRaf = 0

    const reduced = () => reduceMedia?.matches ?? false

    const buildStars = () => {
      const coarse = coarseMedia?.matches ?? false
      const count = width < 640 ? 70 : width < 1024 ? 120 : coarse ? 140 : 180
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.05 + 0.3,
        alpha: Math.random() * 0.42 + 0.18,
        twinkle: Math.random() * 0.0015 + 0.0005,
        phase: Math.random() * Math.PI * 2,
        depth: Math.random() * 0.75 + 0.25,
        warm: Math.random() < 0.18,
      }))
    }

    const paintStar = (star: Star, y: number, alpha: number) => {
      const color = star.warm
        ? `rgba(216,190,147,${alpha.toFixed(3)})`
        : `rgba(245,239,230,${alpha.toFixed(3)})`
      context.fillStyle = color
      if (star.radius < 0.7) {
        const size = star.radius * 2
        context.fillRect(star.x, y, size, size)
      } else {
        context.beginPath()
        context.arc(star.x, y, star.radius, 0, Math.PI * 2)
        context.fill()
      }
      if (star.radius > 1) {
        context.beginPath()
        context.fillStyle = `rgba(216,190,147,${(alpha * 0.2).toFixed(3)})`
        context.arc(star.x, y, star.radius * 3.2, 0, Math.PI * 2)
        context.fill()
      }
    }

    const drawStatic = () => {
      context.clearRect(0, 0, width, height)
      for (const star of stars) paintStar(star, star.y, star.alpha)
    }

    const stop = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
      lastTs = 0
    }

    const draw = (now: number) => {
      raf = 0
      if (!running || reduced()) return
      // 高刷屏上跳过过密帧（约 60–90fps），避免无意义地加倍绘制
      if (lastTs && now - lastTs < 9) {
        raf = requestAnimationFrame(draw)
        return
      }
      const dt = lastTs ? Math.min(now - lastTs, 64) : 16.7
      lastTs = now

      context.clearRect(0, 0, width, height)
      const parallax = scrollY * 0.014
      for (const star of stars) {
        const pulse = Math.sin(now * star.twinkle + star.phase) * 0.16
        const alpha = clamp(star.alpha + pulse, 0.05, 0.9)
        let y = (star.y + parallax * star.depth) % height
        if (y < 0) y += height
        paintStar(star, y, alpha)
      }

      if (!meteor && now > nextMeteorAt) {
        meteor = {
          x: width * (0.12 + Math.random() * 0.62),
          y: height * Math.random() * 0.34,
          vx: 5.4 + Math.random() * 2.6,
          vy: 1.3 + Math.random() * 1.2,
          life: 0,
          maxLife: 820 + Math.random() * 520,
        }
        nextMeteorAt = now + 9000 + Math.random() * 12000
      }

      if (meteor) {
        const step = dt / 16.7
        meteor.x += meteor.vx * step
        meteor.y += meteor.vy * step
        meteor.life += dt
        const progress = meteor.life / meteor.maxLife
        const alpha = Math.sin(Math.PI * clamp(progress, 0, 1)) * 0.82
        const tail = 92
        const gradient = context.createLinearGradient(
          meteor.x,
          meteor.y,
          meteor.x - tail,
          meteor.y - tail * 0.22,
        )
        gradient.addColorStop(0, `rgba(255,246,222,${alpha.toFixed(3)})`)
        gradient.addColorStop(1, 'rgba(255,246,222,0)')
        context.strokeStyle = gradient
        context.lineWidth = 1.5
        context.beginPath()
        context.moveTo(meteor.x, meteor.y)
        context.lineTo(meteor.x - tail, meteor.y - tail * 0.22)
        context.stroke()
        if (meteor.life >= meteor.maxLife) meteor = null
      }

      raf = requestAnimationFrame(draw)
    }

    const start = () => {
      if (raf || !running || reduced()) return
      lastTs = 0
      raf = requestAnimationFrame(draw)
    }

    const resize = () => {
      width = window.innerWidth
      height = window.innerHeight
      dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP)
      canvas.width = Math.max(1, Math.floor(width * dpr))
      canvas.height = Math.max(1, Math.floor(height * dpr))
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      buildStars()
      if (reduced()) drawStatic()
      else start()
    }

    const onResize = () => {
      if (resizeRaf) return
      resizeRaf = requestAnimationFrame(() => {
        resizeRaf = 0
        resize()
      })
    }

    const onScroll = () => {
      // 分屏页滚动发生在 .deck-scroll 内部（scroll 不冒泡，用捕获监听）
      const deck = document.querySelector<HTMLElement>('.deck-scroll')
      scrollY = window.scrollY + (deck ? deck.scrollTop * 0.6 : 0)
    }

    const onVisibility = () => {
      running = document.visibilityState !== 'hidden'
      if (!running) stop()
      else start()
    }

    const offReduced = onMediaChange('(prefers-reduced-motion: reduce)', (matches) => {
      if (matches) {
        stop()
        drawStatic()
      } else {
        start()
      }
    })

    const offCoarse = onMediaChange('(pointer: coarse)', () => {
      buildStars()
      if (reduced()) drawStatic()
    })

    nextMeteorAt = performance.now() + 6000 + Math.random() * 8000
    resize()
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', onScroll, { passive: true, capture: true })
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      stop()
      if (resizeRaf) cancelAnimationFrame(resizeRaf)
      offReduced()
      offCoarse()
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onScroll, true)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={cn('pointer-events-none fixed inset-0 z-0 select-none', className)}
    />
  )
}

export default Starfield
