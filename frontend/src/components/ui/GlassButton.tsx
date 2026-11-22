import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'

type Variant = 'glass' | 'primary' | 'ember' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  /** loading 时给屏幕阅读器的中文提示 */
  loadingLabel?: string
  fullWidth?: boolean
  children?: ReactNode
}

const sizes: Record<Size, string> = {
  sm: 'h-9 px-4 text-[12px]',
  md: 'h-11 px-6 text-[13px]',
  lg: 'h-[52px] px-8 text-[14px]',
}

const variants: Record<Variant, string> = {
  glass: '',
  primary: 'btn-primary',
  ember: 'btn-ember',
  ghost: 'btn-ghost',
}

export function GlassButton({
  variant = 'glass',
  size = 'md',
  loading = false,
  icon,
  loadingLabel = '正在处理，请稍候',
  fullWidth = false,
  className,
  children,
  disabled,
  type,
  ...rest
}: GlassButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'btn-glass',
        sizes[size],
        variants[variant],
        fullWidth && 'w-full',
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
      {loading ? <span className="sr-only">{loadingLabel}</span> : null}
    </button>
  )
}

export default GlassButton
