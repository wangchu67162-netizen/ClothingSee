import { cn } from '@/lib/cn'
import { AgentAvatar } from './AgentAvatar'

export type AgentStatus = 'idle' | 'thinking' | 'done' | 'revised'

export interface AgentCardProps {
  agentId: string
  name: string
  role: string
  color: string
  score?: number
  status?: AgentStatus
  lastMessage?: string
  className?: string
}

const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: '待发言',
  thinking: '思考中',
  done: '已发言',
  revised: '已修订',
}

const STATUS_TEXT: Record<AgentStatus, string> = {
  idle: 'text-ivory/55',
  thinking: 'text-champagne',
  done: 'text-sage',
  revised: 'text-ember',
}

const STATUS_DOT: Record<AgentStatus, string> = {
  idle: 'bg-ivory/25',
  thinking: 'bg-champagne animate-pulse',
  done: 'bg-sage',
  revised: 'bg-ember',
}

export function AgentCard({
  agentId,
  name,
  role,
  color,
  score,
  status = 'idle',
  lastMessage,
  className,
}: AgentCardProps) {
  const hasScore = typeof score === 'number' && Number.isFinite(score)
  return (
    <article
      className={cn(
        'glass-card relative flex min-w-0 flex-col rounded-[20px] p-3.5 text-left',
        status === 'thinking' && 'border-champagne/30',
        className,
      )}
      style={
        status === 'thinking'
          ? { boxShadow: `0 0 0 1px ${color}33, 0 18px 46px ${color}1f` }
          : undefined
      }
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <AgentAvatar agentId={agentId} name={name} color={color} size="md" />
        <div className="min-w-0 flex-1">
          <p className="break-words text-[12px] leading-4 tracking-wide text-ivory">{name}</p>
          <p className="mt-0.5 truncate text-[9px] tracking-[0.08em] text-ivory/55">{role}</p>
        </div>
      </div>

      <div className="mt-2.5 flex min-w-0 items-center gap-1.5 text-[9px]">
        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[status])} />
        <span className={cn('tracking-[0.12em]', STATUS_TEXT[status])}>{STATUS_LABEL[status]}</span>
        {hasScore ? (
          <span
            className="ml-auto shrink-0 rounded-full border px-2 py-0.5 font-display text-[11px]"
            style={{ color, borderColor: `${color}45`, background: `${color}14` }}
            title="本轮平均评分（满分 10）"
          >
            {(score as number).toFixed(1)}
          </span>
        ) : (
          <span className="ml-auto shrink-0 tracking-[0.14em] text-ivory/55">—</span>
        )}
      </div>

      <p className="mt-2 line-clamp-2 min-h-[2.4rem] text-[10px] leading-5 text-ivory/55">
        {lastMessage || '等待发言…'}
      </p>
    </article>
  )
}

export default AgentCard
