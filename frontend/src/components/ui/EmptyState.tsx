import type { ReactNode } from 'react'
import { PackageOpen } from 'lucide-react'
import { cn } from '@/lib/cn'

interface EmptyStateProps {
  icon?: ReactNode
  title?: string
  message?: string
  action?: ReactNode
  className?: string
}

export function EmptyState({
  icon,
  title = '这里还空着',
  message = '暂时没有可展示的内容，换个条件试试。',
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn('flex flex-col items-center justify-center px-6 py-14 text-center', className)}
      role="status"
    >
      <span className="mb-5 flex h-14 w-14 items-center justify-center rounded-full border border-champagne/20 bg-champagne/[0.06] text-champagne/90">
        {icon ?? <PackageOpen className="h-6 w-6" aria-hidden="true" />}
      </span>
      <p className="display text-xl text-ivory/90">{title}</p>
      {message ? <p className="mt-2 max-w-sm text-sm leading-7 text-ivory/55">{message}</p> : null}
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  )
}

export default EmptyState
