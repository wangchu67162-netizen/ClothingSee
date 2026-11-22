import { cn } from '@/lib/cn'
import { agentMeta } from './agents'

export interface AgentAvatarProps {
  agentId?: string
  name?: string
  color?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_CLASS: Record<NonNullable<AgentAvatarProps['size']>, string> = {
  sm: 'h-6 w-6 text-[9px]',
  md: 'h-9 w-9 text-xs',
  lg: 'h-12 w-12 text-sm',
}

export function AgentAvatar({ agentId, name, color, size = 'md', className }: AgentAvatarProps) {
  const meta = agentMeta(agentId, name)
  const tint = color || meta.color
  return (
    <span
      aria-hidden="true"
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center rounded-full border font-display tracking-wide',
        SIZE_CLASS[size],
        className,
      )}
      style={{
        color: tint,
        borderColor: `${tint}55`,
        background: `radial-gradient(circle at 32% 24%, ${tint}30, ${tint}0f 64%, transparent)`,
      }}
    >
      {meta.short}
    </span>
  )
}

export default AgentAvatar
