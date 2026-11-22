import type { ElementType, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

type PanelElement = 'div' | 'section' | 'article' | 'aside' | 'form' | 'nav'

interface GlassPanelProps extends HTMLAttributes<HTMLDivElement> {
  /** 悬浮抬升 + 扫光 */
  hover?: boolean
  strong?: boolean
  /** 仅保留扫光（不抬升） */
  sheen?: boolean
  /** 语义化标签，默认 div */
  as?: PanelElement
  children?: ReactNode
}

export function GlassPanel({
  as = 'div',
  hover = false,
  strong = false,
  sheen = false,
  className,
  children,
  ...rest
}: GlassPanelProps) {
  const Tag = as as ElementType
  return (
    <Tag
      className={cn(
        'glass glass-panel',
        strong && 'glass-strong',
        hover && 'glass-card',
        (hover || sheen) && 'glass-sheen',
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  )
}

export default GlassPanel
