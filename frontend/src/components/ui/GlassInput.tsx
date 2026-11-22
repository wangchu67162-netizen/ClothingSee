import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

interface GlassInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
  icon?: ReactNode
  /** 外层容器附加类名 */
  containerClassName?: string
}

export const GlassInput = forwardRef<HTMLInputElement, GlassInputProps>(function GlassInput(
  { label, error, hint, icon, className, containerClassName, id, ...rest },
  ref,
) {
  const generatedId = useId()
  const inputId = id || rest.name || generatedId
  const hintId = hint ? `${inputId}-hint` : undefined
  const errorId = error ? `${inputId}-error` : undefined
  const describedBy = error ? errorId : hintId

  return (
    <div className={cn('block', containerClassName)}>
      {label && (
        <label
          htmlFor={inputId}
          className="mb-2 block text-[11px] uppercase tracking-[0.24em] text-ivory/55"
        >
          {label}
        </label>
      )}
      <span className="relative block">
        {icon && (
          <span
            className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ivory/55"
            aria-hidden="true"
          >
            {icon}
          </span>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn('input-glass', icon && 'pl-11', error && 'border-ember/70', className)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...rest}
        />
      </span>
      {error ? (
        <span id={errorId} className="mt-1.5 block text-xs text-ember" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={hintId} className="mt-1.5 block text-xs text-ivory/55">
          {hint}
        </span>
      ) : null}
    </div>
  )
})

export default GlassInput
