import { useEffect, useRef } from 'react'
import { Loader2, MessageCircle, RefreshCw } from 'lucide-react'
import type { AgentMessage } from '@/types'
import { cn } from '@/lib/cn'
import { AgentAvatar } from './AgentAvatar'
import { agentMeta } from './agents'

export interface AgentRevision {
  agent: string
  product_id: number
  old_score: number
  new_score: number
  reason?: string
}

export interface AgentTranscriptProps {
  messages: AgentMessage[]
  live?: boolean
  revisions?: AgentRevision[]
  className?: string
}

const TYPE_LABEL: Record<string, string> = {
  opinion: '观点',
  analysis: '分析',
  review: '评议',
  challenge: '质询',
  question: '提问',
  concession: '让步',
  revision: '修订',
  summary: '汇总',
  broadcast: '广播',
  final: '结论',
}

function roundTitle(round: number): string {
  if (round === 1) return 'ROUND 1 · 独立评议'
  if (round === 2) return 'ROUND 2 · 交叉讨论'
  if (round === 3) return 'ROUND 3 · 补充评议'
  return `ROUND ${round} · 圆桌评议`
}

function scoreValue(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function messageTypeLabel(type?: string): string {
  if (!type) return '观点'
  return TYPE_LABEL[type] ?? type
}

export function AgentTranscript({ messages, live = false, revisions = [], className }: AgentTranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = scrollRef.current
    if (!element || messages.length === 0) return
    const frame = window.requestAnimationFrame(() => {
      element.scrollTo({ top: element.scrollHeight, behavior: live ? 'smooth' : 'auto' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [messages.length, live])

  const rounds = new Map<number, AgentMessage[]>()
  for (const message of messages) {
    const round = Number(message.round) || 1
    const bucket = rounds.get(round) ?? []
    bucket.push(message)
    rounds.set(round, bucket)
  }
  const orderedRounds = [...rounds.entries()].sort((a, b) => a[0] - b[0])

  return (
    <div
      ref={scrollRef}
      data-deck-scroll="true"
      className={cn('min-h-0 overflow-y-auto overscroll-contain pr-1', className)}
      aria-live={live ? 'polite' : undefined}
      aria-label="五智能体圆桌记录"
    >
      {messages.length === 0 ? (
        <div className="flex h-full min-h-[240px] flex-col items-center justify-center px-6 text-center">
          {live ? (
            <>
              <Loader2 className="h-7 w-7 animate-spin text-champagne/70" />
              <p className="mt-4 text-sm text-ivory/55">正在召集五位智能体…</p>
              <p className="mt-1.5 max-w-sm text-[11px] leading-6 text-ivory/55">
                它们会先独立评分，再看见彼此的观点、向具名同伴发问，并修正自己的分数。
              </p>
            </>
          ) : (
            <>
              <MessageCircle className="h-8 w-8 text-champagne/35" />
              <p className="display mt-4 text-2xl text-ivory/65">圆桌尚未开始</p>
              <p className="mt-2 max-w-sm text-[11px] leading-6 text-ivory/55">
                上传一张照片后，这里会逐条出现五位智能体的独立观点、互相质询与分数修订。
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-4 pb-2">
          {orderedRounds.map(([round, roundMessages]) => (
            <section key={round} aria-label={roundTitle(round)}>
              <div className="mb-3 flex items-center gap-3 py-1">
                <span className="rounded-full border border-champagne/25 bg-champagne/8 px-2.5 py-1 text-[9px] tracking-[0.16em] text-champagne">
                  {roundTitle(round)}
                </span>
                <span className="h-px flex-1 bg-white/8" />
                <span className="text-[9px] tracking-[0.14em] text-ivory/55">{roundMessages.length} 条</span>
              </div>

              <div className="space-y-2.5">
                {roundMessages.map((message, index) => {
                  const meta = agentMeta(message.agent, message.agent_name)
                  const type = message.message_type || message.role || 'opinion'
                  const isRevision = type === 'revision' || Boolean(message.payload && (message.payload as Record<string, unknown>).old_score !== undefined)
                  const recipients = (message.recipients ?? [])
                    .filter((recipient) => recipient && recipient !== message.agent)
                    .map((recipient) => agentMeta(recipient).name)
                  const scores = (message.scores ?? [])
                    .map((score) => ({ productId: Number(score.product_id), value: scoreValue(score.score), reason: score.reason }))
                    .filter((score) => Number.isFinite(score.productId) && score.value !== null)
                  const payload = (message.payload ?? null) as Record<string, unknown> | null
                  const oldScore = payload ? scoreValue(payload.old_score) : null
                  const newScore = payload ? scoreValue(payload.new_score) : null

                  return (
                    <article
                      key={`${round}-${message.agent}-${message.seq ?? index}-${index}`}
                      className={cn(
                        'rounded-2xl border p-3.5',
                        isRevision
                          ? 'border-champagne/25 bg-champagne/[0.045]'
                          : 'border-white/8 bg-black/20',
                      )}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <AgentAvatar agentId={message.agent} name={meta.name} color={meta.color} size="sm" />
                          <span className="text-xs text-ivory/85" style={{ color: meta.color }}>
                            {message.agent_name || meta.name}
                          </span>
                          {recipients.length > 0 && (
                            <span className="truncate text-[9px] text-ivory/55">
                              → 对 {recipients.slice(0, 3).join('、')} 说
                            </span>
                          )}
                        </div>
                        <span
                          className={cn(
                            'shrink-0 rounded-full border px-2 py-0.5 text-[8px] tracking-[0.14em]',
                            isRevision
                              ? 'border-ember/30 bg-ember/8 text-ember/90'
                              : 'border-white/10 text-ivory/55',
                          )}
                        >
                          {isRevision ? '修订' : messageTypeLabel(type)}
                        </span>
                      </div>

                      <p className="mt-2 text-[13px] leading-6 text-ivory/65">{message.content}</p>

                      {oldScore !== null && newScore !== null && (
                        <p className="mt-2 flex items-center gap-1.5 text-[10px] text-champagne/85">
                          <RefreshCw className="h-3 w-3" />
                          商品 #{String(payload?.product_id ?? '—')} 分数 {oldScore.toFixed(1)} → {newScore.toFixed(1)}
                          {typeof payload?.reason === 'string' && payload.reason ? ` · ${payload.reason}` : ''}
                        </p>
                      )}

                      {scores.length > 0 && (
                        <div className="mt-2.5 flex flex-wrap gap-1.5">
                          {scores.slice(0, 5).map((score) => (
                            <span
                              key={`${message.agent}-${score.productId}`}
                              title={score.reason || undefined}
                              className="rounded-full border border-white/8 bg-white/[0.02] px-2 py-0.5 text-[9px] text-ivory/55"
                            >
                              #{score.productId} · {score.value?.toFixed(1)}
                            </span>
                          ))}
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            </section>
          ))}

          {revisions.length > 0 && (
            <section className="rounded-2xl border border-sage/20 bg-sage/[0.05] p-3.5" aria-label="分数修订汇总">
              <p className="mb-2 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.18em] text-sage">
                <RefreshCw className="h-3 w-3" /> 分数修订 · {revisions.length} 次
              </p>
              <div className="flex flex-wrap gap-1.5">
                {revisions.map((revision, index) => {
                  const meta = agentMeta(revision.agent)
                  return (
                    <span
                      key={`${revision.agent}-${revision.product_id}-${index}`}
                      title={revision.reason || undefined}
                      className="rounded-full border border-sage/20 bg-black/20 px-2.5 py-1 text-[9px] text-sage"
                    >
                      {meta.name} · #{revision.product_id}{' '}
                      {scoreValue(revision.old_score)?.toFixed(1) ?? '—'} →{' '}
                      {scoreValue(revision.new_score)?.toFixed(1) ?? '—'}
                    </span>
                  )
                })}
              </div>
            </section>
          )}

          {live && (
            <p className="flex items-center justify-center gap-2 py-1 text-[10px] text-ivory/55">
              <span className="flex gap-1">
                <span className="h-1 w-1 animate-bounce rounded-full bg-champagne" style={{ animationDelay: '0ms' }} />
                <span className="h-1 w-1 animate-bounce rounded-full bg-champagne" style={{ animationDelay: '120ms' }} />
                <span className="h-1 w-1 animate-bounce rounded-full bg-champagne" style={{ animationDelay: '240ms' }} />
              </span>
              圆桌直播中，等待下一位发言
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default AgentTranscript
