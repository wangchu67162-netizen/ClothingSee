import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowUpRight,
  Cpu,
  GitBranch,
  Layers3,
  RefreshCw,
  ScanLine,
  Sparkles,
} from 'lucide-react'
import { api, apiErrorMessage } from '@/lib/api'
import type { KgEdge, KgGraph, KgNode } from '@/types'
import { cn } from '@/lib/cn'
import { formatPrice } from '@/lib/format'
import { ErrorState, GlassButton, GlassPanel, Loader } from '@/components/ui'
import {
  KGGraph,
  KG_RELATION_OPTIONS,
  kgProductId,
  kgRelationKey,
  type KgRelationKey,
} from '@/components/ai/KGGraph'
import { AuroraField } from '@/components/effects/AuroraField'

interface TextEmbeddingMeta {
  name?: string
  version?: string
  backend?: string
  dim?: number
  status?: string
  loaded?: boolean
  semantic_edges?: number
  top_k?: number
  threshold?: number
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function asText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function nodeImage(node: KgNode): string {
  return asText(asRecord(node.meta).image)
}

function nodePrice(node: KgNode): number | null {
  return asNumber(asRecord(node.meta).price)
}

function nodeCategory(node: KgNode): string {
  return asText(asRecord(node.meta).category)
}

function nodeKind(node: KgNode): string {
  return asText(node.type, 'other')
}

function isProductNode(node: KgNode): boolean {
  return /product|商品|item|sku/i.test(nodeKind(node))
}

function relationCounts(edges: KgEdge[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const edge of edges) {
    const key = kgRelationKey(edge.relation)
    counts[key] = (counts[key] ?? 0) + 1
  }
  return counts
}

function modelMeta(graph: KgGraph | null): TextEmbeddingMeta {
  const meta = asRecord(graph?.meta)
  const embedding = asRecord(meta.text_embedding)
  return {
    name: asText(embedding.name),
    version: asText(embedding.version),
    backend: asText(embedding.backend),
    dim: asNumber(embedding.dim) ?? undefined,
    status: asText(embedding.status),
    loaded: Boolean(embedding.loaded),
    semantic_edges: asNumber(embedding.semantic_edges) ?? undefined,
    top_k: asNumber(embedding.top_k) ?? undefined,
    threshold: asNumber(embedding.threshold) ?? undefined,
  }
}

export default function KnowledgeGraph() {
  const [graph, setGraph] = useState<KgGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [enabledRelations, setEnabledRelations] = useState<Set<KgRelationKey>>(
    () => new Set(KG_RELATION_OPTIONS.map((option) => option.key)),
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get<KgGraph>('/small-models/kg/graph?limit=300', {
        auth: false,
      })
      setGraph(data)
    } catch (cause) {
      setError(apiErrorMessage(cause))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const nodes = useMemo(() => graph?.nodes ?? [], [graph])
  const edges = useMemo(() => graph?.edges ?? [], [graph])
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])
  const productNodes = useMemo(() => nodes.filter(isProductNode), [nodes])
  const attributeCount = Math.max(0, nodes.length - productNodes.length)
  const counts = useMemo(() => relationCounts(edges), [edges])
  const semanticCount = counts.semantic ?? 0
  const embedding = modelMeta(graph)
  const filteredEdges = useMemo(
    () => edges.filter((edge) => enabledRelations.has(kgRelationKey(edge.relation))),
    [edges, enabledRelations],
  )

  const focusId = hoverId ?? selectedId
  const focusNode = focusId ? nodeById.get(focusId) ?? null : null

  const related = useMemo(() => {
    if (!focusNode || !graph) return []
    const seen = new Set<string>()
    const rows: Array<{ edge: KgEdge; node: KgNode }> = []
    for (const edge of graph.edges) {
      if (edge.source !== focusNode.id && edge.target !== focusNode.id) continue
      const otherId = edge.source === focusNode.id ? edge.target : edge.source
      if (seen.has(otherId)) continue
      const other = nodeById.get(otherId)
      if (!other) continue
      seen.add(otherId)
      rows.push({ edge, node: other })
    }
    return rows.sort((left, right) => {
      const priority = (edge: KgEdge) => (kgRelationKey(edge.relation) === 'semantic' ? 0 : 1)
      return (
        priority(left.edge) - priority(right.edge) ||
        Math.abs(right.edge.weight) - Math.abs(left.edge.weight)
      )
    })
  }, [focusNode, graph, nodeById])

  const toggleRelation = (key: KgRelationKey) => {
    setEnabledRelations((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const allEnabled = enabledRelations.size === KG_RELATION_OPTIONS.length
  const toggleAll = () => {
    setEnabledRelations(
      allEnabled
        ? new Set()
        : new Set(KG_RELATION_OPTIONS.map((option) => option.key)),
    )
  }

  return (
    <section className="relative page-pad mx-auto max-w-[1500px] pb-10">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-0 h-[760px] overflow-hidden opacity-100 [mask-image:linear-gradient(180deg,#000_0%,rgba(0,0,0,.72)_68%,transparent_100%)]">
        <AuroraField />
      </div>

      <div className="relative z-10">
        <header className="mb-6 flex flex-col gap-4 md:mb-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <p className="eyebrow flex items-center gap-2 text-[10px] text-cyan-100/70">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              FASHION KNOWLEDGE GRAPH · NLP AURORA
            </p>
            <h1 className="display mt-3 text-balance text-[34px] leading-[1.05] tracking-[0.02em] md:text-[56px]">
              <span className="bg-gradient-to-r from-ivory via-cyan-100 to-champagne bg-clip-text text-transparent">
                服装知识图谱
              </span>
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-ivory/55 md:text-[15px]">
              中文语义模型把每件商品的自然语言描述编码为 512 维向量，视觉向量与词典属性在同一张图中交汇。
              节点不再是抽象圆点——每件衣服都是它的真实照片；点击照片，直接走进商品页。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-cyan-200/20 bg-cyan-300/[0.06] px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.22em] text-cyan-100/75">
              <ScanLine className="h-3.5 w-3.5" aria-hidden="true" />
              AURORA FIELD · LIVE
            </span>
            <GlassButton
              size="sm"
              onClick={() => void load()}
              loading={loading}
              icon={<RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
            >
              重建图谱
            </GlassButton>
          </div>
        </header>

        <div className="mb-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
          {[
            { label: '商品节点', value: productNodes.length, hint: '真实商品图片', icon: Layers3, tone: 'text-champagne' },
            { label: '属性节点', value: attributeCount, hint: '品类 / 材质 / 风格', icon: GitBranch, tone: 'text-cyan-200' },
            { label: '语义边', value: semanticCount, hint: 'BGE 文本余弦', icon: Sparkles, tone: 'text-[#5ef2d6]' },
            { label: '向量维度', value: embedding.dim ?? 512, hint: '中文文本嵌入', icon: Cpu, tone: 'text-violet-200' },
          ].map((stat) => (
            <GlassPanel
              key={stat.label}
              className="relative overflow-hidden rounded-2xl border-white/8 px-4 py-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-ivory/45">
                    {stat.label}
                  </p>
                  <p className={cn('mt-1 font-display text-2xl', stat.tone)}>
                    {stat.value}
                  </p>
                  <p className="mt-0.5 text-[9px] text-ivory/40">{stat.hint}</p>
                </div>
                <stat.icon className="h-4 w-4 text-ivory/30" aria-hidden="true" />
              </div>
            </GlassPanel>
          ))}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_370px]">
          <GlassPanel className="min-w-0 overflow-hidden rounded-[28px] p-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
              <div>
                <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-cyan-100/55">
                  RELATION FILTER // {filteredEdges.length} EDGES
                </p>
                <p className="mt-0.5 text-[10px] text-ivory/45">
                  悬停查看语义，点击商品图片进入商品详情
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={toggleAll}
                  className={cn(
                    'rounded-full border px-2.5 py-1 text-[9px] tracking-[0.08em] transition',
                    allEnabled
                      ? 'border-cyan-200/35 bg-cyan-300/10 text-cyan-100'
                      : 'border-white/10 bg-white/[0.03] text-ivory/45 hover:text-ivory/75',
                  )}
                >
                  {allEnabled ? '收起全部' : '显示全部'}
                </button>
                {KG_RELATION_OPTIONS.map((option) => {
                  const active = enabledRelations.has(option.key)
                  const count = counts[option.key] ?? 0
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => toggleRelation(option.key)}
                      aria-pressed={active}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[9px] tracking-[0.06em] transition',
                        active
                          ? 'border-white/15 bg-white/[0.07] text-ivory/85'
                          : 'border-white/8 bg-black/10 text-ivory/35 hover:text-ivory/60',
                      )}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{
                          background: active ? option.color : 'rgba(245,239,230,.2)',
                          boxShadow: active ? `0 0 8px ${option.color}` : undefined,
                        }}
                      />
                      {option.label}
                      <span className="font-mono text-[8px] text-ivory/35">{count}</span>
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="p-3 md:p-4">
              {loading && !graph ? (
                <div className="flex min-h-[420px] items-center justify-center">
                  <Loader label="NLP 模型正在编码商品语义，构建极光图谱" />
                </div>
              ) : error ? (
                <ErrorState
                  title="图谱暂未点亮"
                  message={error}
                  onRetry={() => void load()}
                  className="border-white/10 bg-black/20"
                />
              ) : graph ? (
                <KGGraph
                  nodes={graph.nodes}
                  edges={filteredEdges}
                  metric={graph.metric}
                  onNodeHover={(node) => setHoverId(node?.id ?? null)}
                  onAttributeClick={(node) => setSelectedId(node.id)}
                />
              ) : null}
            </div>
          </GlassPanel>

          <aside className="flex min-w-0 flex-col gap-3 xl:sticky xl:top-28 xl:self-start">
            <GlassPanel className="overflow-hidden rounded-[26px] border-white/10 p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-ivory/45">
                  NODE INSPECTOR
                </p>
                <span className="inline-flex items-center gap-1.5 font-mono text-[8px] uppercase tracking-[0.2em] text-[#5ef2d6]/75">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#5ef2d6]" />
                  online
                </span>
              </div>

              {focusNode ? (
                isProductNode(focusNode) ? (
                  <div className="mt-3">
                    <div className="flex items-start gap-3">
                      <div className="relative h-24 w-24 shrink-0 overflow-hidden rounded-2xl border border-white/12 bg-black/30">
                        {nodeImage(focusNode) ? (
                          <img
                            src={nodeImage(focusNode)}
                            alt={focusNode.label}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-2xl text-champagne/60">
                            {focusNode.label.slice(0, 1)}
                          </div>
                        )}
                        <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-2 py-1 font-mono text-[8px] tracking-[0.14em] text-cyan-100/80">
                          PRODUCT NODE
                        </span>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[15px] leading-6 text-ivory">{focusNode.label}</p>
                        <p className="mt-1 text-[10px] text-ivory/45">
                          {nodeCategory(focusNode) || '服饰'}
                        </p>
                        <p className="mt-2 font-display text-xl text-champagne">
                          {formatPrice(nodePrice(focusNode))}
                        </p>
                        {kgProductId(focusNode) !== null ? (
                          <Link
                            to={`/product/${kgProductId(focusNode)}`}
                            className="mt-2 inline-flex items-center gap-1 text-[10px] text-cyan-100/75 transition hover:text-cyan-50"
                          >
                            打开商品详情
                            <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
                          </Link>
                        ) : null}
                      </div>
                    </div>

                    <div className="mt-4 border-t border-white/8 pt-3">
                      <p className="font-mono text-[8px] uppercase tracking-[0.22em] text-ivory/40">
                        SEMANTIC NEIGHBORS
                      </p>
                      <div className="mt-2 space-y-1.5">
                        {related
                          .filter((row) => isProductNode(row.node))
                          .slice(0, 4)
                          .map((row) => {
                            const relation = kgRelationKey(row.edge.relation)
                            const option = KG_RELATION_OPTIONS.find((item) => item.key === relation)
                            return (
                              <Link
                                key={`${row.node.id}-${row.edge.relation}`}
                                to={kgProductId(row.node) !== null ? `/product/${kgProductId(row.node)}` : '#'}
                                className="flex items-center gap-2 rounded-xl border border-white/6 bg-white/[0.025] p-1.5 transition hover:border-cyan-200/25 hover:bg-cyan-300/[0.04]"
                              >
                                <span className="h-8 w-8 overflow-hidden rounded-lg bg-black/30">
                                  {nodeImage(row.node) ? (
                                    <img
                                      src={nodeImage(row.node)}
                                      alt=""
                                      className="h-full w-full object-cover"
                                    />
                                  ) : null}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[10px] text-ivory/70">
                                  {row.node.label}
                                </span>
                                <span
                                  className="font-mono text-[8px]"
                                  style={{ color: option?.color ?? '#b9b0a2' }}
                                >
                                  {option?.label ?? '关系'} {row.edge.weight.toFixed(2)}
                                </span>
                              </Link>
                            )
                          })}
                        {related.filter((row) => isProductNode(row.node)).length === 0 ? (
                          <p className="text-[10px] text-ivory/40">暂无商品近邻</p>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="mt-3">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-9 min-w-9 items-center justify-center rounded-xl border border-cyan-200/25 bg-cyan-300/[0.06] px-2 font-mono text-[10px] text-cyan-100/80">
                        {focusNode.label.slice(0, 2)}
                      </span>
                      <div>
                        <p className="text-[14px] text-ivory">{focusNode.label}</p>
                        <p className="font-mono text-[8px] uppercase tracking-[0.18em] text-ivory/40">
                          {nodeKind(focusNode)} NODE
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 space-y-1.5">
                      {related
                        .filter((row) => isProductNode(row.node))
                        .slice(0, 6)
                        .map((row) => (
                          <Link
                            key={row.node.id}
                            to={kgProductId(row.node) !== null ? `/product/${kgProductId(row.node)}` : '#'}
                            className="flex items-center gap-2 rounded-xl border border-white/6 bg-white/[0.025] p-1.5 transition hover:border-cyan-200/25 hover:bg-cyan-300/[0.04]"
                          >
                            <span className="h-8 w-8 overflow-hidden rounded-lg bg-black/30">
                              {nodeImage(row.node) ? (
                                <img src={nodeImage(row.node)} alt="" className="h-full w-full object-cover" />
                              ) : null}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[10px] text-ivory/70">
                              {row.node.label}
                            </span>
                            <span className="font-mono text-[8px] text-ivory/35">
                              {KG_RELATION_OPTIONS.find(
                                (item) => item.key === kgRelationKey(row.edge.relation),
                              )?.label ?? row.edge.relation}
                            </span>
                          </Link>
                        ))}
                    </div>
                  </div>
                )
              ) : (
                <div className="mt-4">
                  <p className="text-sm text-ivory/70">把指针停在任意节点上</p>
                  <p className="mt-1 text-[10px] leading-6 text-ivory/45">
                    商品节点会展开实拍、价格与语义近邻；属性节点会列出与它相连的商品。
                    点击商品图片即可跳转商品详情页。
                  </p>
                  <div className="mt-4 rounded-2xl border border-cyan-200/12 bg-cyan-300/[0.035] p-3">
                    <p className="font-mono text-[8px] uppercase tracking-[0.22em] text-cyan-100/55">
                      TEXT MODEL
                    </p>
                    <p className="mt-1 text-[12px] text-ivory/80">
                      {embedding.name || 'bge-small-zh-v1.5'}
                    </p>
                    <p className="mt-0.5 font-mono text-[8px] text-ivory/40">
                      {embedding.backend || 'onnx-int8'} · {embedding.dim ?? 512} dim ·{' '}
                      {embedding.status || 'ready'}
                    </p>
                    <p className="mt-2 text-[9px] leading-5 text-ivory/45">
                      语义边 = 商品中文描述向量的余弦相似度；阈值{' '}
                      {embedding.threshold?.toFixed(2) ?? '0.55'}，每件取 Top{' '}
                      {embedding.top_k ?? 3}。
                    </p>
                  </div>
                </div>
              )}
            </GlassPanel>

            <GlassPanel className="rounded-[26px] border-white/10 p-4">
              <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-ivory/45">
                RELATION LEGEND
              </p>
              <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                {KG_RELATION_OPTIONS.map((option) => (
                  <div key={option.key} className="flex items-center gap-2">
                    <span
                      className="h-1.5 w-6 rounded-full"
                      style={{
                        background: option.color,
                        boxShadow: `0 0 10px ${option.color}55`,
                      }}
                    />
                    <span className="text-[10px] text-ivory/60">{option.label}</span>
                    <span className="ml-auto font-mono text-[8px] text-ivory/30">
                      {counts[option.key] ?? 0}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 border-t border-white/8 pt-3 text-[9px] leading-5 text-ivory/40">
                实拍节点 = 商品；菱形节点 = 中文 NLP 抽取的品类、材质、风格、场景与颜色。
                图谱由 BGE-small-zh-v1.5 与视觉切比雪夫距离共同生成。
              </p>
            </GlassPanel>
          </aside>
        </div>
      </div>
    </section>
  )
}
