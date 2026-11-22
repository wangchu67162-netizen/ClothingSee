import { createPortal } from 'react-dom'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { useToastStore, type ToastType } from '@/store/toast'
import { cn } from '@/lib/cn'

const icons: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
}

const accents: Record<ToastType, string> = {
  success: 'text-sage',
  error: 'text-ember',
  info: 'text-champagne',
}

const bars: Record<ToastType, string> = {
  success: 'bg-sage/70',
  error: 'bg-ember/80',
  info: 'bg-champagne/70',
}

export function ToastHost() {
  const items = useToastStore((state) => state.items)
  const dismiss = useToastStore((state) => state.dismiss)

  return createPortal(
    <div
      className="pointer-events-none fixed inset-x-0 top-3 z-[200] flex flex-col items-center gap-2 px-4 md:inset-x-auto md:right-6 md:top-6 md:items-end"
      aria-live="polite"
      aria-relevant="additions"
    >
      {items.map((item) => {
        const Icon = icons[item.type]
        return (
          <div
            key={item.id}
            className="toast-in glass-strong pointer-events-auto relative w-full max-w-[380px] overflow-hidden rounded-2xl px-4 py-3.5 pr-10 text-sm"
            role={item.type === 'error' ? 'alert' : 'status'}
          >
            <div className="flex items-start gap-3">
              <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', accents[item.type])} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-ivory">{item.title}</p>
                {item.message ? (
                  <p className="mt-0.5 break-words text-xs leading-5 text-ivory/55">{item.message}</p>
                ) : null}
              </div>
            </div>
            <button
              type="button"
              onClick={() => dismiss(item.id)}
              className="absolute right-2 top-2 rounded-full p-1.5 text-ivory/55 transition hover:bg-white/8 hover:text-ivory"
              aria-label={`关闭提示：${item.title}`}
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            {item.duration > 0 ? (
              <span
                className={cn(
                  'toast-progress pointer-events-none absolute inset-x-0 bottom-0 h-[2px] origin-left',
                  bars[item.type],
                )}
                style={{ animationDuration: `${item.duration}ms` }}
                aria-hidden="true"
              />
            ) : null}
          </div>
        )
      })}
    </div>,
    document.body,
  )
}

export default ToastHost
