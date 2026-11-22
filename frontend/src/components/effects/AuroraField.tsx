import { cn } from '@/lib/cn'
import '@/styles/kg.css'

export interface AuroraFieldProps {
  className?: string
}

/**
 * Vivid aurora backdrop for the fashion knowledge graph.
 * Pure CSS ribbons + grid + star specks, no canvas or external assets.
 */
export function AuroraField({ className }: AuroraFieldProps) {
  return (
    <div className={cn('kg-aurora', className)} aria-hidden="true">
      <span className="kg-aurora__ribbon kg-aurora__ribbon--1" />
      <span className="kg-aurora__ribbon kg-aurora__ribbon--2" />
      <span className="kg-aurora__ribbon kg-aurora__ribbon--3" />
      <span className="kg-aurora__ribbon kg-aurora__ribbon--4" />
      <span className="kg-aurora__grid" />
      <span className="kg-aurora__stars" />
      <span className="kg-aurora__scan" />
    </div>
  )
}

export default AuroraField
