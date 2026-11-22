import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'

export function Loader({ label = '正在加载', className }: { label?: string; className?: string }) {
  return (
    <span
      className={cn('inline-flex items-center gap-2 text-sm text-ivory/55', className)}
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-4 w-4 animate-spin text-champagne" aria-hidden="true" />
      {label}
    </span>
  )
}

export function FullPageLoader({ label = '正在铺开衣橱' }: { label?: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center" role="status" aria-live="polite">
      <Loader label={label} className="text-base" />
    </div>
  )
}

export default Loader
