import type { ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { GlassButton } from './GlassButton'
import { cn } from '@/lib/cn'

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
  retryLabel?: string
  extra?: ReactNode
  className?: string
}

export function ErrorState({
  title = '出了点小问题',
  message = '内容暂时无法加载，请稍后重试。',
  onRetry,
  retryLabel = '重新加载',
  extra,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        'glass glass-panel flex flex-col items-center justify-center px-6 py-12 text-center',
        className,
      )}
      role="alert"
    >
      <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-ember/25 bg-ember/[0.07] text-ember">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
      </span>
      <p className="display text-xl text-ivory/90">{title}</p>
      <p className="mt-2 max-w-md text-sm leading-7 text-ivory/55">{message}</p>
      {extra ? <div className="mt-3 text-xs text-ivory/55">{extra}</div> : null}
      {onRetry ? (
        <GlassButton
          className="mt-6"
          size="sm"
          icon={<RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />}
          onClick={onRetry}
        >
          {retryLabel}
        </GlassButton>
      ) : null}
    </div>
  )
}

export default ErrorState
