import { useEffect, useRef } from 'react'
import { cn } from '@/lib/cn'
import { onMediaChange, queryMedia } from '@/lib/motion'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  life: number
  maxLife: number
  size: number
  sprite: number
  sway: number
}

const PALETTE = ['#FFE0B0', '#FFB36B', '#FF6B3D']
const DPR_CAP = 2
const MAX_PARTICLES = 90

function makeSprite(color: string): HTMLCanvasElement {
  const size = 64
  const sprite = document.createElement('canvas')
  sprite.width = size
  sprite.height = size
  const ctx = sprite.getContext('2d')
  if (!ctx) return sprite
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0, color)
  gradient.addColorStop(0.28, `${color}cc`)
  gradient.addColorStop(0.65, `${color}33`)
  gradient.addColorStop(1, `${color}00`)
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  return sprite
}

export function FlameTrail({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d', { alpha: true })
    if (!context) return

    const coarseMedia = queryMedia('(pointer: coarse)')
    const reduceMedia = queryMedia('(prefers-reduced-motion: reduce)')
    const sprites = PALETTE.map(makeSprite)

    let width = 0
    let height = 0
    let dpr = 1
    let particles: Particle[] = []
    let raf = 0
    let lastTs = 0
    let lastSpawn = 0
    let pointerSeen = false
    let lastPointer = { x: -100, y: -100 }
    let running = document.visibilityState !== 'hidden'
    let resizeRaf = 0

    const enabled = () =>
      running &&
      window.innerWidth >= 768 &&
      !(coarseMedia?.matches ?? false) &&
      !(reduceMedia?.matches ?? false)

    const clearCanvas = () => {
      context.clearRect(0, 0, width, height)
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
      clearCanvas()
    }

    const spawn = (now: number, x: number, y: number) => {
      if (!enabled()) return
      if (now - lastSpawn < 12) return
      lastSpawn = now
      const dx = x - lastPointer.x
      const dy = y - lastPointer.y
      const first = !pointerSeen
      pointerSeen = true
      lastPointer = { x, y }
      const count = first ? 1 : Math.min(4, 1 + Math.floor(Math.hypot(dx, dy) / 10))
      for (let index = 0; index < count; index += 1) {
        if (particles.length >= MAX_PARTICLES) particles.shift()
        const angle = Math.atan2(dy, dx) + Math.PI + (Math.random() - 0.5) * 1.1
        const speed = 0.4 + Math.random() * 1.9
        particles.push({
          x: x + (Math.random() - 0.5) * 10,
          y: y + (Math.random() - 0.5) * 10,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - 0.35,
          life: 0,
          maxLife: 280 + Math.random() * 340,
          size: 8 + Math.random() * 20,
          sprite: Math.floor(Math.random() * sprites.length),
          sway: Math.random() * Math.PI * 2,
        })
      }
    }

    const step = (now: number) => {
      raf = 0
      if (!running) {
        lastTs = 0
        return
      }
      if (lastTs && now - lastTs < 9) {
        raf = requestAnimationFrame(step)
        return
      }
      const dt = lastTs ? Math.min(now - lastTs, 48) : 16.7
      lastTs = now
      const k = dt / 16.7

      clearCanvas()
      context.globalCompositeOperation = 'lighter'
      particles = particles.filter((particle) => particle.life < particle.maxLife)
      for (const particle of particles) {
        particle.life += dt
        particle.x += particle.vx * k + Math.sin((particle.life + particle.sway * 90) / 210) * 0.16 * k
        particle.y += particle.vy * k
        particle.vx *= Math.pow(0.965, k)
        particle.vy = particle.vy * Math.pow(0.965, k) - 0.012 * k
        const progress = Math.min(1, particle.life / particle.maxLife)
        const alpha = Math.pow(1 - progress, 1.7) * 0.92
        const size = particle.size * (1 - progress * 0.45)
        context.globalAlpha = alpha
        context.drawImage(
          sprites[particle.sprite],
          particle.x - size / 2,
          particle.y - size / 2,
          size,
          size,
        )
      }
      context.globalAlpha = 1
      context.globalCompositeOperation = 'source-over'

      if (particles.length) {
        raf = requestAnimationFrame(step)
      } else {
        clearCanvas()
      }
    }

    const start = () => {
      if (raf || !enabled()) return
      lastTs = 0
      raf = requestAnimationFrame(step)
    }

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      if (!enabled()) return
      const now = performance.now()
      spawn(now, event.clientX, event.clientY)
      start()
    }

    const onPointerLeave = () => {
      pointerSeen = false
      lastPointer = { x: -100, y: -100 }
    }

    const onVisibility = () => {
      running = document.visibilityState !== 'hidden'
      if (!running) {
        if (raf) cancelAnimationFrame(raf)
        raf = 0
        lastTs = 0
      } else if (particles.length) {
        start()
      }
    }

    const onResize = () => {
      if (resizeRaf) return
      resizeRaf = requestAnimationFrame(() => {
        resizeRaf = 0
        resize()
      })
    }

    const offCoarse = onMediaChange('(pointer: coarse)', (matches) => {
      if (matches) {
        particles = []
        if (raf) cancelAnimationFrame(raf)
        raf = 0
        clearCanvas()
      }
      pointerSeen = false
    })

    const offReduced = onMediaChange('(prefers-reduced-motion: reduce)', (matches) => {
      if (matches) {
        particles = []
        if (raf) cancelAnimationFrame(raf)
        raf = 0
        clearCanvas()
      }
      pointerSeen = false
    })

    resize()
    window.addEventListener('resize', onResize)
    window.addEventListener('pointermove', onPointerMove, { passive: true })
    document.addEventListener('pointerleave', onPointerLeave)
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      if (raf) cancelAnimationFrame(raf)
      if (resizeRaf) cancelAnimationFrame(resizeRaf)
      offCoarse()
      offReduced()
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('pointerleave', onPointerLeave)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={cn(
        'flame-trail pointer-events-none fixed inset-0 z-[80] hidden select-none md:block',
        className,
      )}
    />
  )
}

export default FlameTrail
