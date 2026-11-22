import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  MessageCircle,
  RefreshCw,
  Sparkles,
  Square,
  Users,
} from 'lucide-react'
import { PageDeck, type DeckSection } from '@/components/layout/PageDeck'
import {
  AGENT_META,
  AGENT_ORDER,
  AgentCard,
  AgentTranscript,
  KGGraph,
  UploadDrop,
  type AgentRevision,
  type AgentStatus,
} from '@/components/ai'
import { GlassButton, GlassPanel, ImageWithFallback, PriceTag } from '@/components/ui'
import { postSSE } from '@/lib/sse'
import { apiErrorMessage } from '@/lib/api'
import { formatPrice } from '@/lib/format'
import { useCartStore } from '@/store/cart'
import { useToast } from '@/store/toast'
import { cn } from '@/lib/cn'
import type {
  AgentMessage,
  KgEdge,
  KgGraph,
  KgNode,
  Product,
  RecommendationFinal,
  VisionAnalysis,
} from '@/types'

const STAGE_DEFS = [
  { key: 'vision', label: '视觉解析' },
  { key: 'retrieval', label: '小模型检索' },
  { key: 'round1', label: '第一轮评议' },
  { key: 'round2', label: '第二轮互评' },
  { key: 'aggregate', label: '最终汇总' },
] as const

const PIPELINE = [
  { title: '上传照片', detail: '一张穿搭照，告诉造型室你想去的场合' },
  { title: '看懂与检索', detail: 'Qwen-VL 解析 + 视觉小模型 / NLP-KG 找候选' },
  { title: '五智圆桌', detail: '两轮具名互评，允许修订最多 2 个分数' },
  { title: '整套提案', detail: 'Top3 + 整套穿搭 + 中文造型建议 + 知识图谱' },
]

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function normalizeKg(input: unknown): KgGraph | null {
  const record = asRecord(input)
  const nodes: KgNode[] = []
  const edges: KgEdge[] = []
  const rawNodes = Array.isArray(record.nodes) ? record.nodes : []
  const rawEdges = Array.isArray(record.edges) ? record.edges : []

  for (const item of rawNodes) {
    const node = asRecord(item)
    const rawId = node.id
    const id = typeof rawId === 'string' ? rawId : rawId != null ? String(rawId) : ''
    if (!id) continue
    nodes.push({
      id,
      label: typeof node.label === 'string' && node.label ? node.label : id,
      type: typeof node.type === 'string' && node.type ? node.type : 'other',
    })
  }

  for (const item of rawEdges) {
    const edge = asRecord(item)
    const source = typeof edge.source === 'string' ? edge.source : edge.source != null ? String(edge.source) : ''
    const target = typeof edge.target === 'string' ? edge.target : edge.target != null ? String(edge.target) : ''
    if (!source || !target) continue
    edges.push({
      source,
      target,
      relation: typeof edge.relation === 'string' ? edge.relation : 'related',
      weight: Number.isFinite(Number(edge.weight)) ? Number(edge.weight) : 0.3,
    })
  }

  if (!nodes.length) return null
  return { nodes, edges, metric: typeof record.metric === 'string' ? record.metric : 'chebyshev' }
}

function confidencePercent(value?: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value * 100)))
}

function scoreText(value: unknown): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(1) : '—'
}

function elapsedText(value: unknown): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? (parsed / 1000).toFixed(1) : '0.0'
}

export function Stylist() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [budget, setBudget] = useState('')
  const [note, setNote] = useState('')

  const [running, setRunning] = useState(false)
  const [mode, setMode] = useState('mock')
  const [sessionId, setSessionId] = useState('')
  const [stage, setStage] = useState('')
  const [roundLabel, setRoundLabel] = useState('')

  const [vision, setVision] = useState<VisionAnalysis | null>(null)
  const [candidates, setCandidates] = useState<Product[]>([])
  const [candidateMeta, setCandidateMeta] = useState<{ metric?: string; backend?: string }>({})
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [revisions, setRevisions] = useState<AgentRevision[]>([])
  const [kg, setKg] = useState<KgGraph | null>(null)
  const [kgSummary, setKgSummary] = useState('')
  const [final, setFinal] = useState<RecommendationFinal | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const addToCart = useCartStore((state) => state.add)
  const toast = useToast()

  useEffect(() => {
    if (!file) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => () => abortRef.current?.abort(), [])

  const resetResults = () => {
    setVision(null)
    setCandidates([])
    setCandidateMeta({})
    setMessages([])
    setRevisions([])
    setKg(null)
    setKgSummary('')
    setFinal(null)
    setError(null)
    setWarning(null)
    setStage('')
    setRoundLabel('')
    setSessionId('')
  }

  const chooseFile = (next: File) => {
    setFile(next)
    resetResults()
  }

  const clearFile = () => {
    setFile(null)
    resetResults()
  }

  const goTo = (id: string) => {
    const element = document.getElementById(id)
    element?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const handleEvent = (name: string, payload: unknown) => {
    const data = asRecord(payload)
    switch (name) {
      case 'session': {
        if (typeof data.session_id === 'string') setSessionId(data.session_id)
        if (typeof data.mode === 'string') setMode(data.mode)
        break
      }
      case 'stage': {
        if (typeof data.stage === 'string') setStage(data.stage)
        break
      }
      case 'vision': {
        const source = data.vision && typeof data.vision === 'object' ? data.vision : data
        setVision(source as unknown as VisionAnalysis)
        break
      }
      case 'candidates': {
        const raw = Array.isArray(data.items) ? data.items : Array.isArray(payload) ? payload : []
        setCandidates(raw.filter((item): item is Product => Boolean(item && (item as Product).id)))
        setCandidateMeta({
          metric: typeof data.metric === 'string' ? data.metric : undefined,
          backend: typeof data.backend === 'string' ? data.backend : undefined,
        })
        break
      }
      case 'kg': {
        const source = data.graph && typeof data.graph === 'object' ? data.graph : data
        const graph = normalizeKg(source)
        if (graph) setKg(graph)
        if (typeof data.summary === 'string') setKgSummary(data.summary)
        break
      }
      case 'agent_round': {
        if (typeof data.round === 'number') setStage(data.round >= 2 ? 'round2' : 'round1')
        if (typeof data.label === 'string') setRoundLabel(data.label)
        break
      }
      case 'agent_message': {
        const source = (data.message && typeof data.message === 'object' ? data.message : data) as unknown as AgentMessage
        if (!source || typeof source.content !== 'string') break
        const message: AgentMessage = {
          ...source,
          agent_name: source.agent_name || (typeof data.agent_name === 'string' ? data.agent_name : ''),
        }
        setMessages((current) => [...current, message])
        if (typeof message.round === 'number') {
          setStage((current) => (current === 'aggregate' ? current : message.round >= 2 ? 'round2' : 'round1'))
        }
        break
      }
      case 'revision': {
        const agent = typeof data.agent === 'string' ? data.agent : ''
        const productId = Number(data.product_id)
        if (!agent || !Number.isFinite(productId)) break
        const oldScore = Number(data.old_score)
        const newScore = Number(data.new_score)
        setRevisions((current) => [
          ...current,
          {
            agent,
            product_id: productId,
            old_score: Number.isFinite(oldScore) ? oldScore : 0,
            new_score: Number.isFinite(newScore) ? newScore : 0,
            reason: typeof data.reason === 'string' ? data.reason : '',
          },
        ])
        break
      }
      case 'final': {
        const source = data.final && typeof data.final === 'object' ? data.final : data
        setFinal(source as unknown as RecommendationFinal)
        setStage('aggregate')
        break
      }
      case 'warning': {
        const message = typeof data.message === 'string' && data.message ? data.message : '部分步骤已降级'
        setWarning(message)
        toast.info('提示', message)
        break
      }
      case 'error': {
        const message = typeof data.message === 'string' && data.message ? data.message : '推荐失败，请稍后重试'
        setError(message)
        toast.error('推荐失败', message)
        break
      }
      case 'done': {
        setStage((current) => current || 'aggregate')
        break
      }
      default:
        break
    }
  }

  const run = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!file || running) return
    setRunning(true)
    setError(null)
    setWarning(null)
    setFinal(null)
    setMessages([])
    setRevisions([])
    setCandidates([])
    setCandidateMeta({})
    setVision(null)
    setKg(null)
    setKgSummary('')
    setStage('vision')
    setRoundLabel('')

    const form = new FormData()
    form.append('file', file)
    if (budget.trim()) form.append('budget', budget.trim())
    if (note.trim()) form.append('note', note.trim())

    const controller = new AbortController()
    abortRef.current = controller
    try {
      await postSSE('/recommend/image', form, (sseEvent) => handleEvent(sseEvent.event, sseEvent.data), {
        signal: controller.signal,
      })
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        const detail = apiErrorMessage(reason)
        setError(detail)
        toast.error('推荐失败', detail)
      }
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    setRunning(false)
    setWarning('已停止本次共议，可以重新上传照片再试。')
    toast.info('已停止', '本次五智共议已中止')
  }

  const addProduct = async (product: Product) => {
    try {
      await addToCart(product.id, {
        quantity: 1,
        size: product.sizes?.[0] ?? '',
        color: product.colors?.[0] ?? '',
      })
      toast.success('已放入购物袋', product.name)
    } catch (reason) {
      toast.error('加入失败', apiErrorMessage(reason))
    }
  }

  const agentStatus = (agentId: string): AgentStatus => {
    if (revisions.some((revision) => revision.agent === agentId)) return 'revised'
    const own = messages.filter((message) => message.agent === agentId)
    if (final) return 'done'
    if (!own.length) {
      return running && (stage === 'round1' || stage === 'round2') ? 'thinking' : 'idle'
    }
    const latestRound = Math.max(...own.map((message) => Number(message.round) || 1))
    if (running && stage === 'round2' && latestRound < 2) return 'thinking'
    return 'done'
  }

  const agentScore = (agentId: string): number | undefined => {
    const own = messages.filter((message) => message.agent === agentId)
    for (let index = own.length - 1; index >= 0; index -= 1) {
      const values = (own[index].scores ?? [])
        .map((score) => Number(score.score))
        .filter((value) => Number.isFinite(value))
      if (values.length) {
        return values.reduce((sum, value) => sum + value, 0) / values.length
      }
    }
    return undefined
  }

  const agentLastMessage = (agentId: string): string | undefined =>
    messages.filter((message) => message.agent === agentId).slice(-1)[0]?.content

  const stageIndex = stage ? STAGE_DEFS.findIndex((item) => item.key === stage) : -1
  const effectiveStage = final ? STAGE_DEFS.length - 1 : stageIndex
  const stageDone = (index: number) => Boolean(final) || (effectiveStage >= 0 && index < effectiveStage)
  const stageActive = (index: number) => running && effectiveStage === index
  const stageLabel = STAGE_DEFS[Math.max(0, effectiveStage)]?.label ?? (running ? '准备中' : '待开始')

  const finalKg = final ? normalizeKg(final.kg) : null
  const activeKg = finalKg ?? kg
  const canEnterRound = running || messages.length > 0 || Boolean(final)
  const canViewFinal = Boolean(final)

  const sections: DeckSection[] = [
    {
      id: 'studio-upload',
      label: '上传照片',
      content: (
        <div data-deck-scroll="true" className="h-full min-h-0 overflow-y-auto overscroll-contain">
          <div className="mx-auto flex min-h-full w-full max-w-[1340px] flex-col justify-center py-2">
            <div className="grid items-center gap-6 lg:grid-cols-[0.94fr_1.06fr]">
              <div>
                <p className="eyebrow mb-3">THE ROUND TABLE · FIVE AGENTS</p>
                <h1 className="display text-[clamp(2.6rem,5.6vw,5.2rem)] leading-[0.96] text-ivory">
                  五智造型室
                </h1>
                <p className="mt-4 max-w-lg text-[13px] leading-7 text-ivory/55">
                  上传一张照片。视觉小模型先检索相似款，NLP 知识图谱以切比雪夫距离扩展搭配，五位智能体再围绕你展开两轮真实讨论。
                </p>

                <div className="mt-6 hidden space-y-3 sm:block">
                  {PIPELINE.map((item, index) => {
                    const isUpload = index === 0
                    const active =
                      running &&
                      ((index === 1 && (stage === 'vision' || stage === 'retrieval')) ||
                        (index === 2 && (stage === 'round1' || stage === 'round2')))
                    const done =
                      (isUpload && Boolean(file)) ||
                      (index === 1 && Boolean(vision || candidates.length)) ||
                      (index === 2 && messages.length > 0) ||
                      (index === 3 && Boolean(final))
                    return (
                      <div key={item.title} className="flex items-start gap-3">
                        <span
                          className={cn(
                            'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[9px]',
                            done
                              ? 'border-sage/30 bg-sage/10 text-sage'
                              : active
                                ? 'border-champagne/40 bg-champagne/10 text-champagne'
                                : 'border-white/10 bg-white/[0.02] text-ivory/55',
                          )}
                        >
                          {done ? (
                            <Check className="h-3 w-3" />
                          ) : active ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            `0${index + 1}`
                          )}
                        </span>
                        <div>
                          <p className={cn('text-[12px]', done || active ? 'text-ivory/80' : 'text-ivory/55')}>
                            {item.title}
                          </p>
                          <p className="mt-0.5 text-[10px] leading-5 text-ivory/55">{item.detail}</p>
                        </div>
                      </div>
                    )
                  })}
                </div>

                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      'rounded-full border px-3 py-1 text-[9px] tracking-[0.14em]',
                      mode === 'qwen'
                        ? 'border-sage/30 bg-sage/10 text-sage'
                        : 'border-champagne/25 bg-champagne/8 text-champagne',
                    )}
                  >
                    {mode === 'qwen' ? 'QWEN 多模态 · 在线' : 'MOCK 演示模式'}
                  </span>
                  <span className="rounded-full border border-white/10 px-3 py-1 text-[9px] tracking-[0.14em] text-ivory/55">
                    图片仅用于本次演示
                  </span>
                </div>

                {(running || messages.length > 0) && (
                  <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-champagne/15 bg-champagne/[0.04] px-3.5 py-2.5">
                    <Loader2 className={cn('h-3.5 w-3.5 text-champagne', running && 'animate-spin')} />
                    <p className="text-[10px] text-ivory/55">
                      当前：{stageLabel}
                      {messages.length > 0 ? ` · 已收到 ${messages.length} 条发言` : ''}
                    </p>
                    <button
                      type="button"
                      onClick={() => goTo('studio-roundtable')}
                      className="ml-auto inline-flex items-center gap-1 text-[10px] text-champagne/90 transition hover:text-champagne"
                    >
                      查看圆桌 <ArrowRight className="h-3 w-3" />
                    </button>
                  </div>
                )}

                {error && (
                  <div className="mt-4 flex items-start gap-2 rounded-2xl border border-ember/25 bg-ember/[0.06] px-3.5 py-2.5 text-[11px] leading-5 text-ember/90">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
                  </div>
                )}
                {warning && (
                  <div className="mt-2 flex items-start gap-2 rounded-2xl border border-champagne/20 bg-champagne/[0.04] px-3.5 py-2.5 text-[10px] leading-5 text-champagne/80">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {warning}
                  </div>
                )}
              </div>

              <GlassPanel strong className="rounded-[28px] p-4 md:p-5">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <p className="text-sm text-ivory">上传你的照片</p>
                    <p className="mt-0.5 text-[9px] tracking-[0.16em] text-ivory/55">拖入 / 点击 / 使用样例图</p>
                  </div>
                  <span className="rounded-full border border-champagne/25 bg-champagne/8 px-2.5 py-1 text-[8px] tracking-[0.14em] text-champagne/90">
                    第一步 · UPLOAD
                  </span>
                </div>

                <UploadDrop onFile={chooseFile} onClear={clearFile} loading={running} />

                <form onSubmit={run} className="mt-4 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="mb-1.5 block text-[9px] uppercase tracking-[0.2em] text-ivory/55">
                        预算（选填）
                      </span>
                      <input
                        value={budget}
                        onChange={(event) => setBudget(event.target.value.replace(/[^\d.]/g, ''))}
                        inputMode="decimal"
                        placeholder="例如 1500"
                        className="input-glass h-10 text-sm"
                        disabled={running}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1.5 block text-[9px] uppercase tracking-[0.2em] text-ivory/55">
                        场合 / 偏好（选填）
                      </span>
                      <input
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="通勤、约会、显高…"
                        maxLength={200}
                        className="input-glass h-10 text-sm"
                        disabled={running}
                      />
                    </label>
                  </div>

                  <div className="flex gap-2">
                    <GlassButton
                      type="submit"
                      variant="primary"
                      className="flex-1"
                      loading={running}
                      disabled={!file}
                      icon={<Sparkles className="h-4 w-4" />}
                    >
                      {running ? '五位智能体正在共议…' : file ? '开始五智共议' : '请先选择照片'}
                    </GlassButton>
                    {running ? (
                      <GlassButton type="button" variant="ghost" onClick={stop} aria-label="停止本次共议">
                        <Square className="h-4 w-4" />
                      </GlassButton>
                    ) : (
                      <GlassButton
                        type="button"
                        variant="ghost"
                        onClick={() => goTo('studio-analysis')}
                        aria-label="前往视觉解析"
                      >
                        <ArrowRight className="h-4 w-4" />
                      </GlassButton>
                    )}
                  </div>
                </form>

                <p className="mt-3 border-t border-white/8 pt-3 text-[9px] leading-5 text-ivory/55">
                  视觉小模型负责检索、NLP 小模型负责知识图谱与切比雪夫距离；大模型负责理解与表达。没有 API Key 时全链路自动使用 Mock。
                </p>
              </GlassPanel>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'studio-analysis',
      label: '视觉解析',
      content: (
        <div data-deck-scroll="true" className="h-full min-h-0 overflow-y-auto overscroll-contain">
          <div className="mx-auto flex min-h-full w-full max-w-[1380px] flex-col justify-center gap-5 py-2">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="eyebrow mb-2">VISION & SMALL MODELS</p>
                <h2 className="display text-[clamp(2rem,4.2vw,3.6rem)] leading-none text-ivory">
                  先看懂照片，再检索衣裳
                </h2>
                <p className="mt-2 max-w-2xl text-[11px] leading-6 text-ivory/55">
                  Qwen-VL（或 Mock）输出品类 / 色彩 / 风格 / 材质 / 场合；视觉小模型给出 Top-8 候选，NLP-KG 以切比雪夫距离扩展关系。
                </p>
              </div>
              <div className="flex items-center gap-2">
                <GlassButton size="sm" variant="ghost" icon={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => goTo('studio-upload')}>
                  返回上传
                </GlassButton>
                <GlassButton
                  size="sm"
                  variant="primary"
                  icon={<Users className="h-3.5 w-3.5" />}
                  onClick={() => goTo('studio-roundtable')}
                  disabled={!canEnterRound}
                >
                  前往圆桌
                </GlassButton>
              </div>
            </div>

            {error && (
              <div className="flex items-start gap-2 rounded-2xl border border-ember/25 bg-ember/[0.06] px-3.5 py-2.5 text-[11px] leading-5 text-ember/90">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
              </div>
            )}
            {warning && (
              <div className="flex items-start gap-2 rounded-2xl border border-champagne/20 bg-champagne/[0.04] px-3.5 py-2.5 text-[10px] leading-5 text-champagne/80">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {warning}
              </div>
            )}

            <div className="grid gap-4 lg:grid-cols-[0.86fr_1.14fr]">
              <div className="space-y-4">
                <GlassPanel className="overflow-hidden rounded-[24px]">
                  <div className="relative">
                    {preview ? (
                      <img src={preview} alt="本次上传的穿搭照" className="h-40 w-full object-cover md:h-48" />
                    ) : (
                      <div className="flex h-40 flex-col items-center justify-center gap-2 bg-black/20 text-ivory/55 md:h-48">
                        <Sparkles className="h-6 w-6 text-champagne/40" />
                        <p className="text-[11px]">尚未上传照片</p>
                      </div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-3 py-2 text-[9px] text-ivory/60">
                      <span className="truncate">{file?.name || '等待上传'}</span>
                      <span>{running ? '解析中…' : vision ? '解析完成' : '待解析'}</span>
                    </div>
                  </div>
                </GlassPanel>

                <GlassPanel className="rounded-[24px] p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="eyebrow text-[9px]">视觉解析 · VISION</p>
                    <span className="text-[9px] text-ivory/55">
                      {vision ? `置信度 ${confidencePercent(vision.confidence)}%` : '等待结果'}
                    </span>
                  </div>

                  {vision ? (
                    <>
                      <p className="text-[12px] leading-6 text-ivory/65">{vision.summary || '已完成图片理解。'}</p>
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/8">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-champagne/60 to-champagne"
                          style={{ width: `${confidencePercent(vision.confidence)}%` }}
                        />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {[vision.category, ...(vision.colors ?? []), ...(vision.style ?? []), ...(vision.material ?? []), vision.occasion]
                          .filter(Boolean)
                          .map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[9px] text-ivory/55"
                            >
                              {tag}
                            </span>
                          ))}
                      </div>
                      {(vision.body_hints || vision.occasion) && (
                        <p className="mt-3 border-t border-white/8 pt-2.5 text-[10px] leading-5 text-ivory/55">
                          {vision.occasion ? `场合线索：${vision.occasion}。` : ''}
                          {vision.body_hints ? `身形线索：${vision.body_hints}。` : ''}
                        </p>
                      )}
                    </>
                  ) : running ? (
                    <div className="flex items-center gap-2 py-5 text-[11px] text-ivory/55">
                      <Loader2 className="h-4 w-4 animate-spin text-champagne/80" />
                      正在阅读照片，识别品类、颜色、材质与场合…
                    </div>
                  ) : (
                    <p className="py-4 text-[11px] leading-6 text-ivory/55">
                      上传照片并点击「开始五智共议」后，这里会显示 Qwen-VL / Mock 的结构化解析结果。
                    </p>
                  )}
                </GlassPanel>
              </div>

              <div className="space-y-4">
                <GlassPanel className="rounded-[24px] p-4">
                  <div className="mb-2.5 flex items-center justify-between gap-2">
                    <div>
                      <p className="eyebrow text-[9px]">小模型候选 · TOP 8</p>
                      <p className="mt-0.5 text-[9px] text-ivory/55">
                        {candidateMeta.metric ? `度量 ${candidateMeta.metric} · ${candidateMeta.backend ?? 'stub'}` : '视觉相似度检索'}
                      </p>
                    </div>
                    <span className="rounded-full border border-sage/25 bg-sage/8 px-2.5 py-1 text-[9px] text-sage">
                      {candidates.length} 个候选
                    </span>
                  </div>

                  {candidates.length > 0 ? (
                    <div className="space-y-1.5">
                      {candidates.slice(0, 8).map((product, index) => (
                        <Link
                          key={product.id}
                          to={`/product/${product.id}`}
                          className="group flex items-center gap-2.5 rounded-xl border border-transparent px-2 py-1.5 transition hover:border-white/10 hover:bg-white/[0.03]"
                        >
                          <span className="w-4 shrink-0 text-[9px] text-ivory/55">{String(index + 1).padStart(2, '0')}</span>
                          <ImageWithFallback
                            src={product.image}
                            alt={product.name}
                            className="h-11 w-9 shrink-0 rounded-lg object-cover"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[11px] text-ivory/75 transition group-hover:text-champagne">
                              {product.name}
                            </p>
                            <p className="truncate text-[9px] text-ivory/55">
                              {product.category} · {product.fabric || product.subtitle}
                            </p>
                          </div>
                          <div className="shrink-0 text-right">
                            <p className="text-[11px] text-champagne/90">{formatPrice(product.price)}</p>
                            {typeof product.similarity === 'number' && Number.isFinite(product.similarity) ? (
                              <p className="text-[8px] text-ivory/55">
                                相似度 {product.similarity <= 1 ? `${Math.round(product.similarity * 100)}%` : product.similarity.toFixed(2)}
                              </p>
                            ) : null}
                          </div>
                        </Link>
                      ))}
                    </div>
                  ) : running ? (
                    <div className="flex items-center gap-2 py-6 text-[11px] text-ivory/55">
                      <Loader2 className="h-4 w-4 animate-spin text-champagne/80" />
                      视觉小模型正在切比雪夫空间里找相似款…
                    </div>
                  ) : (
                    <p className="py-5 text-[11px] leading-6 text-ivory/55">
                      候选商品会在这里出现，点击可查看详情。
                    </p>
                  )}
                </GlassPanel>

                <GlassPanel className="rounded-[24px] p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="eyebrow text-[9px]">知识图谱 · CHEBYSHEV</p>
                    <span className="text-[9px] text-ivory/55">
                      {activeKg ? `${activeKg.nodes.length} 节点 / ${activeKg.edges.length} 关系` : '等待构建'}
                    </span>
                  </div>
                  {activeKg ? (
                    <KGGraph
                      nodes={activeKg.nodes}
                      edges={activeKg.edges}
                      metric={activeKg.metric}
                      className="min-h-[240px]"
                      compact
                    />
                  ) : (
                    <div className="flex min-h-[180px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-black/20 px-5 text-center">
                      <RefreshCw className={cn('h-5 w-5 text-champagne/40', running && 'animate-spin')} />
                      <p className="mt-2 text-[10px] leading-5 text-ivory/55">
                        {running ? 'NLP 小模型正在抽取属性并连边…' : '检索完成后显示商品与属性的知识图谱。'}
                      </p>
                    </div>
                  )}
                  {kgSummary && <p className="mt-2 text-[9px] leading-5 text-ivory/55">{kgSummary}</p>}
                </GlassPanel>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'studio-roundtable',
      label: '五智圆桌',
      content: (
        <div className="flex h-full min-h-0 flex-col gap-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow mb-1.5">LIVE · THE ROUND TABLE</p>
              <h2 className="display text-[clamp(1.9rem,4vw,3.4rem)] leading-none text-ivory">五位智能体，正在共议</h2>
              <p className="mt-1.5 max-w-2xl text-[10px] leading-5 text-ivory/55">
                Round 1 独立评分；Round 2 看到彼此观点，向具名同伴发言，并允许修订最多 2 个分数。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-white/10 px-2.5 py-1 text-[9px] text-ivory/55">
                会话 {sessionId ? sessionId.slice(0, 8) : '等待开始'}
              </span>
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[9px]',
                  running ? 'border-sage/30 bg-sage/10 text-sage' : 'border-white/10 text-ivory/55',
                )}
              >
                <span className={cn('h-1.5 w-1.5 rounded-full', running ? 'animate-pulse bg-sage' : 'bg-ivory/30')} />
                {running ? '实时直播' : '直播结束'}
              </span>
              <GlassButton size="sm" variant="ghost" icon={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => goTo('studio-analysis')}>
                返回解析
              </GlassButton>
              <GlassButton
                size="sm"
                variant="primary"
                icon={<ArrowRight className="h-3.5 w-3.5" />}
                onClick={() => goTo('studio-final')}
                disabled={!canViewFinal}
              >
                最终方案
              </GlassButton>
            </div>
          </div>

          <div className="flex items-center gap-1.5 overflow-x-auto rounded-full border border-white/8 bg-white/[0.025] p-1.5 scrollbar-none">
            {STAGE_DEFS.map((item, index) => (
              <div
                key={item.key}
                className={cn(
                  'flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[9px] tracking-[0.08em]',
                  stageDone(index)
                    ? 'bg-sage/10 text-sage'
                    : stageActive(index)
                      ? 'bg-champagne/12 text-champagne'
                      : 'text-ivory/55',
                )}
              >
                <span
                  className={cn(
                    'flex h-4 w-4 items-center justify-center rounded-full text-[8px]',
                    stageDone(index) ? 'bg-sage/20' : stageActive(index) ? 'bg-champagne/20' : 'bg-white/5',
                  )}
                >
                  {stageDone(index) ? (
                    <Check className="h-2.5 w-2.5" />
                  ) : stageActive(index) ? (
                    <Loader2 className="h-2.5 w-2.5 animate-spin" />
                  ) : (
                    index + 1
                  )}
                </span>
                {item.label}
              </div>
            ))}
            {(roundLabel || stage === 'round1' || stage === 'round2') && (
              <span className="ml-auto shrink-0 pr-2 text-[9px] text-ivory/55">{roundLabel || '圆桌评议中'}</span>
            )}
          </div>

          {(error || warning) && (
            <div className="flex flex-wrap gap-2">
              {error && (
                <p className="flex items-center gap-1.5 rounded-full border border-ember/25 bg-ember/[0.06] px-3 py-1.5 text-[10px] text-ember/85">
                  <AlertCircle className="h-3 w-3" /> {error}
                </p>
              )}
              {warning && (
                <p className="flex items-center gap-1.5 rounded-full border border-champagne/20 bg-champagne/[0.04] px-3 py-1.5 text-[10px] text-champagne/80">
                  <AlertTriangle className="h-3 w-3" /> {warning}
                </p>
              )}
            </div>
          )}

          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none lg:grid lg:grid-cols-5 lg:gap-3">
            {AGENT_ORDER.map((agentId) => {
              const meta = AGENT_META[agentId]
              return (
                <AgentCard
                  key={agentId}
                  agentId={agentId}
                  name={meta.name}
                  role={meta.role}
                  color={meta.color}
                  score={agentScore(agentId)}
                  status={agentStatus(agentId)}
                  lastMessage={agentLastMessage(agentId)}
                  className="w-[190px] shrink-0 lg:w-auto"
                />
              )
            })}
          </div>

          <GlassPanel strong className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[26px]">
            <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
              <div className="flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-champagne/80" />
                <div>
                  <p className="text-[12px] text-ivory">圆桌记录</p>
                  <p className="text-[9px] tracking-[0.14em] text-ivory/55">
                    {running ? 'LIVE · 逐条实时推送' : 'TRANSCRIPT'} · {messages.length} 条
                  </p>
                </div>
              </div>
              <span className="text-[9px] text-ivory/55">
                {revisions.length > 0 ? `${revisions.length} 次分数修订` : '尚无修订'}
              </span>
            </div>

            <AgentTranscript
              messages={messages}
              revisions={revisions}
              live={running}
              className="flex-1 min-h-0 px-3 py-3 md:px-4"
            />

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 px-4 py-2.5">
              <p className="text-[9px] text-ivory/55">
                记录区可独立滚动；滚到边界后继续滚动即可翻页。
              </p>
              <GlassButton
                size="sm"
                variant={final ? 'primary' : 'glass'}
                icon={<Sparkles className="h-3.5 w-3.5" />}
                onClick={() => goTo('studio-final')}
                disabled={!canViewFinal}
              >
                {final ? '查看最终整套方案' : '等待最终汇总…'}
              </GlassButton>
            </div>
          </GlassPanel>
        </div>
      ),
    },
    {
      id: 'studio-final',
      label: '最终方案',
      content: (
        <div data-deck-scroll="true" className="h-full min-h-0 overflow-y-auto overscroll-contain">
          <div className="mx-auto flex min-h-full w-full max-w-[1400px] flex-col justify-center gap-4 py-2">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="eyebrow mb-1.5">THE CURATION · TOP 3</p>
                <h2 className="display text-[clamp(1.9rem,4vw,3.4rem)] leading-none text-ivory">这一组，是我们的答案</h2>
                <p className="mt-1.5 text-[10px] text-ivory/55">
                  {final
                    ? `耗时 ${elapsedText(final.elapsed_ms)}s · ${final.mode === 'qwen' ? 'Qwen 模式' : 'Mock 演示模式'} · 聚合器加权五智评分`
                    : '完成共议后，Top3、整套穿搭与知识图谱会出现在这里。'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <GlassButton size="sm" variant="ghost" icon={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => goTo('studio-roundtable')}>
                  返回圆桌
                </GlassButton>
                <GlassButton size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => goTo('studio-upload')}>
                  重新上传
                </GlassButton>
              </div>
            </div>

            {final ? (
              <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
                <div className="space-y-3">
                  <GlassPanel strong className="rounded-[24px] p-4 md:p-5">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-champagne/80" />
                      <p className="eyebrow text-[9px]">造型建议 · STYLING NOTES</p>
                    </div>
                    <p className="mt-2 text-[13px] leading-7 text-ivory/65">
                      {final.advice || '聚合器没有返回文字建议，但下面的整套搭配仍然可以作为参考。'}
                    </p>

                    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/8 pt-3">
                      <span className="text-[9px] uppercase tracking-[0.16em] text-ivory/55">整套提案</span>
                      {(final.outfit ?? []).map((product) => (
                        <Link
                          key={product.id}
                          to={`/product/${product.id}`}
                          className="flex items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] py-1 pl-1 pr-3 transition hover:border-champagne/30"
                        >
                          <ImageWithFallback
                            src={product.image}
                            alt={product.name}
                            className="h-6 w-5 rounded-full object-cover"
                          />
                          <span className="text-[10px] text-ivory/55">{product.name}</span>
                        </Link>
                      ))}
                      {(final.outfit ?? []).length === 0 && (
                        <span className="text-[10px] text-ivory/55">整套提案整理中</span>
                      )}
                      <span className="ml-auto text-sm text-champagne">合计 {formatPrice(final.outfit_total)}</span>
                    </div>
                  </GlassPanel>

                  <div className="grid gap-3 sm:grid-cols-3">
                    {(final.recommendations ?? []).slice(0, 3).map((item, index) => (
                      <GlassPanel key={item.product.id} className="group overflow-hidden rounded-[22px]">
                        <div className="relative overflow-hidden">
                          <ImageWithFallback
                            src={item.product.image}
                            alt={item.product.name}
                            className="aspect-[4/5] w-full object-cover transition duration-700 group-hover:scale-[1.03]"
                          />
                          <span className="absolute left-2.5 top-2.5 flex h-6 w-6 items-center justify-center rounded-full border border-champagne/40 bg-black/50 font-display text-[10px] text-champagne backdrop-blur">
                            {index + 1}
                          </span>
                          <span className="absolute right-2.5 top-2.5 rounded-full border border-white/15 bg-black/50 px-2 py-0.5 text-[9px] text-ivory/75 backdrop-blur">
                            {scoreText(item.score)} 分
                          </span>
                        </div>
                        <div className="p-3">
                          <p className="truncate text-[12px] text-ivory">{item.product.name}</p>
                          <div className="mt-1">
                            <PriceTag price={item.product.price} originalPrice={item.product.original_price} size="sm" />
                          </div>
                          <ul className="mt-2 space-y-1">
                            {(item.reasons ?? []).slice(0, 3).map((reason) => (
                              <li key={reason} className="flex gap-1.5 text-[9px] leading-4 text-ivory/55">
                                <span className="text-champagne/70">·</span>
                                <span className="line-clamp-2">{reason}</span>
                              </li>
                            ))}
                          </ul>
                          <div className="mt-2.5 flex items-center gap-2">
                            <GlassButton size="sm" className="flex-1" onClick={() => void addProduct(item.product)}>
                              加入购物袋
                            </GlassButton>
                            <Link
                              to={`/product/${item.product.id}`}
                              className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 text-ivory/55 transition hover:border-champagne/30 hover:text-champagne"
                              aria-label={`查看 ${item.product.name} 详情`}
                            >
                              <ArrowRight className="h-3.5 w-3.5" />
                            </Link>
                          </div>
                        </div>
                      </GlassPanel>
                    ))}
                  </div>

                  {(final.recommendations ?? []).length === 0 && (
                    <p className="rounded-2xl border border-white/8 bg-black/20 px-4 py-5 text-center text-[11px] text-ivory/55">
                      聚合器没有返回 Top3，可能因为本次候选不足。可返回圆桌查看评议记录，或重新上传照片。
                    </p>
                  )}
                </div>

                <GlassPanel className="flex flex-col rounded-[26px] p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <div>
                      <p className="eyebrow text-[9px]">KNOWLEDGE GRAPH</p>
                      <p className="mt-0.5 text-[9px] text-ivory/55">商品·属性·搭配关系 · 切比雪夫距离</p>
                    </div>
                    <span className="rounded-full border border-sage/25 bg-sage/8 px-2.5 py-1 text-[8px] text-sage">
                      {activeKg ? `${activeKg.nodes.length} 节点` : '未生成'}
                    </span>
                  </div>
                  {activeKg ? (
                    <KGGraph
                      nodes={activeKg.nodes}
                      edges={activeKg.edges}
                      metric={activeKg.metric}
                      className="min-h-[280px] flex-1"
                      compact
                    />
                  ) : (
                    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-black/20 px-5 py-10 text-center">
                      <RefreshCw className="h-5 w-5 text-champagne/40" />
                      <p className="mt-2 text-[10px] leading-5 text-ivory/55">
                        本次没有返回知识图谱，可查看候选列表与圆桌记录。
                      </p>
                    </div>
                  )}
                  <p className="mt-2 text-[9px] leading-5 text-ivory/55">
                    {kgSummary || '视觉向量 Top-3 近邻建立 similar_to 边；上装与下装之间建立搭配边，辅助整套推荐。'}
                  </p>
                </GlassPanel>
              </div>
            ) : (
              <GlassPanel strong className="flex flex-col items-center justify-center rounded-[28px] px-6 py-12 text-center">
                <span className="flex h-16 w-16 items-center justify-center rounded-full border border-white/10 bg-white/[0.025] text-champagne/50">
                  {running ? <Loader2 className="h-6 w-6 animate-spin" /> : <Sparkles className="h-6 w-6" />}
                </span>
                <p className="display mt-4 text-2xl text-ivory/70">
                  {running ? '正在汇总这一组答案' : '方案还没有生成'}
                </p>
                <p className="mt-2 max-w-md text-[11px] leading-6 text-ivory/55">
                  {running
                    ? `当前进行到「${stageLabel}」，已收到 ${messages.length} 条智能体发言。最终方案到达后会自动出现在这里。`
                    : '先上传一张照片并开始五智共议，Top3、整套穿搭、造型建议与知识图谱会一起出现在这里。'}
                </p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  <GlassButton size="sm" icon={<ArrowLeft className="h-3.5 w-3.5" />} onClick={() => goTo('studio-roundtable')}>
                    查看圆桌
                  </GlassButton>
                  <GlassButton size="sm" variant="primary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => goTo('studio-upload')}>
                    重新上传
                  </GlassButton>
                </div>
              </GlassPanel>
            )}
          </div>
        </div>
      ),
    },
  ]

  return <PageDeck sections={sections} />
}

export default Stylist
