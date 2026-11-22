import { useEffect, useState } from 'react'
import { AlertTriangle, Camera, Check, Loader2, Maximize2, X } from 'lucide-react'
import type { BrowseStep } from '@/types'
import { cn } from '@/lib/cn'

export interface ToolTraceProps {
  steps: BrowseStep[]
  className?: string
}

interface LightboxState {
  src: string
  label: string
}

const STATUS_TEXT: Record<BrowseStep['status'], string> = {
  running: '进行中',
  done: '完成',
  failed: '失败',
}

function screenshotUrl(path?: string | null): string {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path
  return path.startsWith('/') ? path : `/${path}`
}

export function ToolTrace({ steps, className }: ToolTraceProps) {
  const [lightbox, setLightbox] = useState<LightboxState | null>(null)

  useEffect(() => {
    if (!lightbox) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLightbox(null)
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [lightbox])

  return (
    <div className={cn('min-h-0 overflow-y-auto overscroll-contain', className)}>
      {steps.length === 0 ? (
        <div className="flex h-full min-h-[260px] flex-col items-center justify-center px-6 text-center">
          <span className="flex h-16 w-16 items-center justify-center rounded-full border border-white/10 bg-white/[0.025] text-champagne/50">
            <Camera className="h-6 w-6" />
          </span>
          <p className="display mt-5 text-2xl text-ivory/70">每一步都留下截图</p>
          <p className="mt-2 max-w-xs text-[11px] leading-6 text-ivory/55">
            当你说“帮我下单”，助理会打开云裳商城，依次截图：搜索、商品页、选择规格、结算、下单成功。
          </p>
        </div>
      ) : (
        <ol className="space-y-3">
          {steps.map((step, index) => {
            const screenshot = screenshotUrl(step.screenshot)
            return (
              <li
                key={`${step.index}-${step.action}-${index}`}
                className="overflow-hidden rounded-2xl border border-white/10 bg-black/20"
              >
                <div className="flex items-center justify-between gap-3 px-3 py-2.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn(
                        'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px]',
                        step.status === 'failed' && 'bg-ember/15 text-ember',
                        step.status === 'running' && 'bg-champagne/15 text-champagne',
                        step.status === 'done' && 'bg-sage/15 text-sage',
                      )}
                    >
                      {step.status === 'failed' ? (
                        <AlertTriangle className="h-3 w-3" />
                      ) : step.status === 'running' ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Check className="h-3 w-3" />
                      )}
                    </span>
                    <p className="truncate text-[11px] text-ivory/70">{step.action}</p>
                  </div>
                  <span
                    className={cn(
                      'shrink-0 text-[9px] tracking-[0.14em]',
                      step.status === 'failed'
                        ? 'text-ember/80'
                        : step.status === 'running'
                          ? 'text-champagne/90'
                          : 'text-sage',
                    )}
                  >
                    {STATUS_TEXT[step.status]}
                  </span>
                </div>

                {step.detail && <p className="px-3 pb-2 text-[10px] leading-5 text-ivory/55">{step.detail}</p>}

                {screenshot && (
                  <button
                    type="button"
                    onClick={() => setLightbox({ src: screenshot, label: step.action })}
                    className="group relative block w-full border-t border-white/8"
                    aria-label={`放大查看截图：${step.action}`}
                  >
                    <img
                      src={screenshot}
                      alt={`浏览器步骤截图：${step.action}`}
                      loading="lazy"
                      className="h-28 w-full object-cover object-top opacity-90 transition duration-500 group-hover:opacity-100"
                    />
                    <span className="absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-full border border-white/15 bg-black/55 px-2 py-1 text-[9px] text-ivory/70 backdrop-blur">
                      <Maximize2 className="h-2.5 w-2.5" /> 查看大图
                    </span>
                  </button>
                )}
              </li>
            )
          })}
        </ol>
      )}

      {lightbox && (
        <div
          className="fixed inset-0 z-[140] flex flex-col items-center justify-center bg-black/85 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label={`截图灯箱：${lightbox.label}`}
        >
          <button
            type="button"
            className="absolute inset-0 cursor-zoom-out"
            onClick={() => setLightbox(null)}
            aria-label="关闭截图灯箱"
          />
          <div className="relative z-[1] flex max-h-full w-full max-w-5xl flex-col gap-3">
            <div className="flex items-center justify-between gap-4">
              <p className="text-sm text-ivory/80">{lightbox.label}</p>
              <div className="flex items-center gap-2">
                <a
                  href={lightbox.src}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-white/15 px-3 py-1.5 text-[10px] text-ivory/60 transition hover:border-champagne/40 hover:text-champagne"
                >
                  在新标签页打开
                </a>
                <button
                  type="button"
                  onClick={() => setLightbox(null)}
                  className="rounded-full border border-white/15 p-2 text-ivory/70 transition hover:bg-white/10"
                  aria-label="关闭"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <img
              src={lightbox.src}
              alt={lightbox.label}
              className="max-h-[78vh] w-full rounded-2xl border border-white/12 object-contain shadow-2xl"
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default ToolTrace
