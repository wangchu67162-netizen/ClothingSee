import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Bot,
  Camera,
  ScanSearch,
  Send,
  Sparkles,
  Square,
  User,
} from 'lucide-react'
import type { AssistantIntent, AssistantProductCard, AssistantTurn, BrowseStep } from '@/types'
import { postSSE } from '@/lib/sse'
import { apiErrorMessage } from '@/lib/api'
import { ProductLinkCard, ToolTrace } from '@/components/ai'
import { GlassButton, GlassPanel } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import { useToast } from '@/store/toast'
import { cn } from '@/lib/cn'

interface ChatTurn extends AssistantTurn {
  error?: string
  warnings?: string[]
}

const QUICK = [
  '我想买一件适合秋天的风衣',
  '帮我找一条能配真丝衬衫的阔腿裤',
  '帮我下单暮色长风衣，M 码',
  '推荐一条适合晚宴的裙子',
]

const INTENT_LABEL: Record<string, string> = {
  recommend: '找商品',
  order: '下单',
  chat: '咨询',
  unknown: '识别中',
}

const INITIAL: ChatTurn = {
  role: 'assistant',
  content:
    '你好，我是衣见购物助理。可以帮你找带图的商品链接，也可以直接打开无头浏览器替你下单。试试说：「帮我下单暮色长风衣，M 码」。',
  status: 'done',
}

function shortenId(id?: string): string {
  if (!id) return '新会话'
  return id.length > 10 ? `${id.slice(0, 8)}…` : id
}

export function Assistant() {
  const user = useAuthStore((state) => state.user)
  const navigate = useNavigate()
  const toast = useToast()
  const [turns, setTurns] = useState<ChatTurn[]>([INITIAL])
  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>()
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  useEffect(() => () => abortRef.current?.abort(), [])

  const patchLast = (patch: Partial<ChatTurn> | ((turn: ChatTurn) => Partial<ChatTurn>)) => {
    setTurns((current) => {
      if (!current.length) return current
      const copy = [...current]
      const last = copy[copy.length - 1]
      const update = typeof patch === 'function' ? patch(last) : patch
      copy[copy.length - 1] = { ...last, ...update }
      return copy
    })
  }

  const handleEvent = (name: string, payload: unknown) => {
    const data = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>
    switch (name) {
      case 'session': {
        if (typeof data.session_id === 'string') setSessionId(data.session_id)
        break
      }
      case 'intent': {
        const intent = data.intent
        if (intent === 'recommend' || intent === 'order' || intent === 'chat' || intent === 'unknown') {
          patchLast({
            intent: {
              intent,
              query: typeof data.query === 'string' ? data.query : '',
              size: typeof data.size === 'string' ? data.size : '',
              color: typeof data.color === 'string' ? data.color : '',
              confidence: typeof data.confidence === 'number' ? data.confidence : undefined,
            } satisfies AssistantIntent,
          })
        }
        break
      }
      case 'assistant_message': {
        const full = typeof data.content === 'string' ? data.content : ''
        const delta = typeof data.delta === 'string' ? data.delta : ''
        if (full) patchLast({ content: full })
        else if (delta) patchLast((turn) => ({ content: `${turn.content ?? ''}${delta}` }))
        break
      }
      case 'products': {
        const raw = Array.isArray(data.items)
          ? (data.items as AssistantProductCard[])
          : Array.isArray(payload)
            ? (payload as AssistantProductCard[])
            : []
        const items = raw.filter((item) => item && typeof item === 'object' && item.product)
        patchLast({ products: items })
        break
      }
      case 'browse_step': {
        if (!data.action || typeof data.index !== 'number') break
        const step = data as unknown as BrowseStep
        patchLast((turn) => {
          const steps = turn.steps ?? []
          const existing = steps.findIndex((item) => item.index === step.index)
          const next =
            existing >= 0
              ? steps.map((item, index) => (index === existing ? { ...item, ...step } : item))
              : [...steps, step]
          return { steps: next }
        })
        break
      }
      case 'order_created': {
        const orderNo = typeof data.order_no === 'string' ? data.order_no : ''
        if (orderNo) {
          patchLast({ orderNo, status: 'done' })
          toast.success('下单成功', `订单号 ${orderNo}`)
        } else {
          patchLast({
            status: 'error',
            error: '浏览器流程已结束，但服务端没有返回订单号。请先到「我的订单」确认，不要重复提交。',
          })
        }
        break
      }
      case 'warning': {
        const message = typeof data.message === 'string' && data.message ? data.message : '部分步骤已降级'
        patchLast((turn) => ({ warnings: [...(turn.warnings ?? []), message] }))
        toast.info('提示', message)
        break
      }
      case 'error': {
        const message = typeof data.message === 'string' && data.message ? data.message : '处理失败，请稍后重试'
        patchLast({ status: 'error', error: message })
        toast.error('处理失败', message)
        break
      }
      case 'done': {
        patchLast((turn) => {
          if (turn.status === 'error') return {}
          const content =
            turn.content ||
            (turn.orderNo
              ? '下单流程已完成，订单已写入平台订单。'
              : turn.products && turn.products.length > 0
                ? '以上是为你挑到的商品。'
                : '处理完成。')
          return { status: 'done', content }
        })
        break
      }
      default:
        break
    }
  }

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || running) return
    if (!user) {
      navigate(`/auth?next=${encodeURIComponent('/assistant')}`)
      return
    }
    setInput('')
    setRunning(true)
    setTurns((current) => [
      ...current,
      { role: 'user', content: message, status: 'done' },
      { role: 'assistant', content: '', status: 'streaming', steps: [] },
    ])

    const controller = new AbortController()
    abortRef.current = controller
    try {
      await postSSE(
        '/assistant/chat',
        { message, session_id: sessionId },
        (event) => handleEvent(event.event, event.data),
        { signal: controller.signal },
      )
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        const detail = apiErrorMessage(error)
        patchLast({ status: 'error', error: detail })
        toast.error('连接失败', detail)
      }
    } finally {
      setRunning(false)
      abortRef.current = null
      patchLast((turn) =>
        turn.status === 'streaming'
          ? {
              status: 'done',
              content:
                turn.content ||
                (turn.orderNo
                  ? '下单流程已完成。'
                  : turn.products && turn.products.length > 0
                    ? '以上是为你挑到的商品。'
                    : '已为你完成本次检索。'),
            }
          : {},
      )
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void send(input)
  }

  const stop = () => {
    abortRef.current?.abort()
    setRunning(false)
    patchLast((turn) =>
      turn.status === 'streaming'
        ? {
            status: 'done',
            content: turn.content || '已停止本次操作。',
            warnings: [...(turn.warnings ?? []), '操作已被手动停止'],
          }
        : {},
    )
  }

  const lastAssistant = [...turns].reverse().find((turn) => turn.role === 'assistant')
  const activeSteps =
    [...turns].reverse().find((turn) => turn.role === 'assistant' && (turn.steps?.length ?? 0) > 0)?.steps ?? []
  const lastOrder = [...turns].reverse().find((turn) => turn.orderNo)?.orderNo
  const latestIntent = [...turns].reverse().find((turn) => turn.role === 'assistant' && turn.intent)?.intent

  return (
    <div className="page-pad mx-auto max-w-[1500px]">
      <header className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow mb-2">CONCIERGE · SINGLE AGENT + BROWSER</p>
          <h1 className="display text-[clamp(2.2rem,4.6vw,4rem)] leading-none text-ivory">AI 购物助理</h1>
          <p className="mt-2 hidden max-w-2xl text-[12px] leading-6 text-ivory/55 sm:block">
            它能看到衣橱，也能打开无头浏览器。找链接、比款式、直接下单，整个过程都在右侧留下截图证据。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-sage/25 bg-sage/8 px-3 py-1.5 text-[9px] tracking-[0.14em] text-sage">
            PLAYWRIGHT · 无头模式
          </span>
          <span className="rounded-full border border-champagne/25 bg-champagne/8 px-3 py-1.5 text-[9px] tracking-[0.14em] text-champagne">
            云裳商城 · 模拟支付
          </span>
          {latestIntent && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[9px] tracking-[0.12em] text-ivory/55">
              <ScanSearch className="h-3 w-3 text-champagne/70" />
              意图 · {INTENT_LABEL[latestIntent.intent] ?? latestIntent.intent}
            </span>
          )}
        </div>
      </header>

      <div className="grid gap-4 lg:h-[calc(100dvh-17rem)] lg:min-h-[560px] lg:grid-cols-[1.12fr_0.88fr]">
        <GlassPanel
          strong
          className="flex h-[68dvh] min-h-[520px] flex-col overflow-hidden rounded-[28px] lg:h-full lg:min-h-0"
        >
          <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3.5 md:px-5">
            <div className="flex min-w-0 items-center gap-3">
              <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ember/12 text-ember">
                <Bot className="h-4 w-4" />
                <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-sage shadow-[0_0_10px_rgba(110,139,134,.8)]" />
              </span>
              <div className="min-w-0">
                <p className="text-sm text-ivory">衣见购物助理</p>
                <p className="truncate text-[9px] tracking-[0.16em] text-ivory/55">
                  {running ? '正在执行任务…' : '在线 · 随时待命'} · 会话 {shortenId(sessionId)}
                </p>
              </div>
            </div>
            {lastAssistant?.orderNo ? (
              <span className="shrink-0 rounded-full border border-sage/30 bg-sage/10 px-2.5 py-1 text-[9px] tracking-[0.1em] text-sage">
                本轮已下单
              </span>
            ) : (
              <span className="shrink-0 rounded-full border border-white/10 px-2.5 py-1 text-[9px] text-ivory/55">
                浏览器取证
              </span>
            )}
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 md:px-5" aria-live="polite">
            {turns.map((turn, index) =>
              turn.role === 'user' ? (
                <div key={index} className="flex items-start justify-end gap-2">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-champagne/14 px-4 py-2.5 text-[13px] leading-6 text-ivory/90">
                    {turn.content}
                  </div>
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/8 text-ivory/55">
                    <User className="h-3.5 w-3.5" />
                  </span>
                </div>
              ) : (
                <div key={index} className="flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ember/10 text-ember">
                    <Bot className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 max-w-[92%] flex-1">
                    {turn.intent && (
                      <span className="mb-1.5 inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[9px] tracking-[0.1em] text-ivory/55">
                        <ScanSearch className="h-2.5 w-2.5 text-champagne/70" />
                        意图 · {INTENT_LABEL[turn.intent.intent] ?? turn.intent.intent}
                        {turn.intent.query ? ` · ${turn.intent.query}` : ''}
                      </span>
                    )}

                    {(turn.content || (turn.status === 'streaming' && !turn.error)) && (
                      <div className="rounded-2xl rounded-bl-md border border-white/8 bg-white/[0.035] px-4 py-2.5 text-[13px] leading-6 text-ivory/75">
                        {turn.content || (
                          <span className="flex items-center gap-2 text-ivory/55">
                            <span className="flex gap-1">
                              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-champagne" style={{ animationDelay: '0ms' }} />
                              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-champagne" style={{ animationDelay: '120ms' }} />
                              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-champagne" style={{ animationDelay: '240ms' }} />
                            </span>
                            {turn.steps && turn.steps.length > 0 ? '正在浏览器中执行…' : '正在理解你的需求…'}
                          </span>
                        )}
                      </div>
                    )}

                    {turn.error && (
                      <div className="mt-2 flex items-start gap-2 rounded-2xl border border-ember/30 bg-ember/[0.06] px-3.5 py-3 text-[11px] leading-6 text-ember/90">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <div>
                          <p className="font-medium">本次操作未完成</p>
                          <p className="mt-0.5 text-ember/90">{turn.error}</p>
                        </div>
                      </div>
                    )}

                    {turn.products && turn.products.length > 0 && (
                      <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
                        {turn.products.slice(0, 6).map((item) => (
                          <ProductLinkCard key={item.product.id} item={item} />
                        ))}
                      </div>
                    )}

                    {turn.orderNo && (
                      <div className="mt-2.5 rounded-2xl border border-sage/30 bg-sage/[0.07] p-3.5">
                        <div className="flex items-center gap-2 text-[12px] text-sage">
                          <BadgeCheck className="h-4 w-4" />
                          下单成功 · 云裳商城（模拟支付）
                        </div>
                        <p className="mt-1.5 text-[11px] text-ivory/55">
                          订单号{' '}
                          <span className="font-mono text-[14px] tracking-[0.08em] text-ivory">{turn.orderNo}</span>
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px]">
                          <Link
                            to="/orders"
                            className="inline-flex items-center gap-1 text-champagne/90 transition hover:text-champagne"
                          >
                            查看我的订单 <ArrowRight className="h-3 w-3" />
                          </Link>
                          <a
                            href={`/demo-mall/success.html?order_no=${encodeURIComponent(turn.orderNo)}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-ivory/55 transition hover:text-sage"
                          >
                            打开商城成功页
                          </a>
                        </div>
                      </div>
                    )}

                    {turn.warnings && turn.warnings.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {turn.warnings.map((warning, warningIndex) => (
                          <p
                            key={`${warningIndex}-${warning}`}
                            className="flex items-start gap-1.5 text-[10px] leading-5 text-champagne/70"
                          >
                            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                            {warning}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-white/8 p-3 md:p-4">
            <div className="mb-2.5 flex gap-2 overflow-x-auto pb-1 scrollbar-none">
              {QUICK.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => void send(prompt)}
                  disabled={running}
                  className="shrink-0 rounded-full border border-white/10 px-3 py-1.5 text-[10px] text-ivory/55 transition hover:border-champagne/30 hover:text-champagne disabled:opacity-40"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <form onSubmit={onSubmit} className="flex items-end gap-2">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="告诉助理你想买什么，或让它帮你下单…"
                className="input-glass h-11 flex-1 rounded-full"
                disabled={running}
                maxLength={512}
                aria-label="给购物助理发消息"
              />
              {running ? (
                <GlassButton
                  type="button"
                  variant="glass"
                  className="h-11 w-11 shrink-0 rounded-full p-0"
                  onClick={stop}
                  aria-label="停止本次任务"
                >
                  <Square className="h-4 w-4" />
                </GlassButton>
              ) : (
                <GlassButton
                  type="submit"
                  variant="primary"
                  className="h-11 w-11 shrink-0 rounded-full p-0"
                  disabled={!input.trim()}
                  aria-label="发送消息"
                >
                  <Send className="h-4 w-4" />
                </GlassButton>
              )}
            </form>
            <p className="mt-2 flex items-center gap-1.5 text-[9px] text-ivory/55">
              <Sparkles className="h-2.5 w-2.5" /> 只有收到真实订单号才会显示「下单成功」，失败会明确告诉你原因。
            </p>
          </div>
        </GlassPanel>

        <GlassPanel className="flex h-[58dvh] min-h-[420px] flex-col overflow-hidden rounded-[26px] lg:h-full lg:min-h-0">
          <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3.5 md:px-5">
            <div className="min-w-0">
              <p className="text-sm text-ivory">浏览器取证</p>
              <p className="truncate text-[9px] tracking-[0.16em] text-ivory/55">
                TOOL TRACE · SCREENSHOTS · {activeSteps.length} 步
              </p>
            </div>
            <Camera className="h-4 w-4 shrink-0 text-champagne/70" />
          </div>

          {lastOrder && (
            <div className="flex items-center gap-2 border-b border-sage/20 bg-sage/[0.06] px-4 py-2.5 text-[10px] text-sage">
              <BadgeCheck className="h-3.5 w-3.5" />
              最近一次成功订单 · {lastOrder}
            </div>
          )}

          <ToolTrace steps={activeSteps} className={cn('flex-1 p-3 md:p-4', activeSteps.length === 0 && 'flex flex-col')} />

          <div className="border-t border-white/8 px-4 py-2.5 text-[9px] leading-5 text-ivory/55">
            云裳商城为项目内置模拟商城，不连接真实电商与支付；截图路径来自后端运行目录。
          </div>
        </GlassPanel>
      </div>
    </div>
  )
}

export default Assistant
