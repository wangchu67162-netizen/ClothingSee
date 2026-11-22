import { useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { KgEdge, KgNode } from '@/types'
import { cn } from '@/lib/cn'
import { AuroraField } from '@/components/effects/AuroraField'
import '@/styles/kg.css'

export interface KGGraphProps {
  nodes: KgNode[]
  edges: KgEdge[]
  metric?: string
  className?: string
  /** Smaller image nodes for the in-page stylist card. */
  compact?: boolean
  showLegend?: boolean
  onNodeHover?: (node: KgNode | null) => void
  onAttributeClick?: (node: KgNode) => void
}

type NodeKind =
  | 'product'
  | 'category'
  | 'color'
  | 'style'
  | 'material'
  | 'occasion'
  | 'attribute'
  | 'other'

const KIND_LABEL: Record<NodeKind, string> = {
  product: '商品',
  category: '品类',
  color: '颜色',
  style: '风格',
  material: '材质',
  occasion: '场景',
  attribute: '属性',
  other: '其他',
}

const KIND_COLOR: Record<NodeKind, string> = {
  product: '#ffd9a0',
  category: '#7fc8ff',
  color: '#ff7a59',
  style: '#b79cff',
  material: '#f2c48d',
  occasion: '#71e6d2',
  attribute: '#9ef7e4',
  other: '#f5efe6',
}

const CATEGORY_COLOR: Record<string, string> = {
  外套: '#7fc8ff',
  上装: '#ffd9a0',
  连衣裙: '#f4a7cf',
  下装: '#7dd8b6',
  配饰: '#ff9a76',
}

const MAX_PRODUCTS = 18
const MAX_OTHERS = 160
const MAX_EDGES = 420
const VIEW_W = 1000
const VIEW_H = 620
const CX = VIEW_W / 2
const CY = VIEW_H / 2 + 5

type RelationKey =
  | 'semantic'
  | 'similar'
  | 'pair'
  | 'category'
  | 'color'
  | 'material'
  | 'style'
  | 'occasion'
  | 'size'
  | 'other'

interface EdgeStyle {
  label: string
  color: string
  glow: boolean
  flow: boolean
  width: number
  priority: number
}

const EDGE_STYLE: Record<RelationKey, EdgeStyle> = {
  semantic: { label: '语义相似', color: '#5ef2d6', glow: true, flow: true, width: 1.9, priority: 0 },
  similar: { label: '视觉相似', color: '#d8be93', glow: false, flow: true, width: 1.45, priority: 1 },
  pair: { label: '搭配', color: '#7dd8b6', glow: false, flow: true, width: 1.3, priority: 2 },
  category: { label: '品类', color: '#7fc8ff', glow: false, flow: false, width: 0.95, priority: 3 },
  color: { label: '颜色', color: '#ff8b68', glow: false, flow: false, width: 0.85, priority: 4 },
  material: { label: '材质', color: '#f2c48d', glow: false, flow: false, width: 0.85, priority: 5 },
  style: { label: '风格', color: '#b79cff', glow: false, flow: false, width: 0.85, priority: 6 },
  occasion: { label: '场景', color: '#71e6d2', glow: false, flow: false, width: 0.85, priority: 7 },
  size: { label: '尺码', color: '#b9b0a2', glow: false, flow: false, width: 0.7, priority: 8 },
  other: { label: '关系', color: '#f5efe6', glow: false, flow: false, width: 0.7, priority: 9 },
}

function relationKey(relation?: string): RelationKey {
  const raw = (relation || '').toLowerCase()
  if (/semantic|语义/.test(raw)) return 'semantic'
  if (/similar|相似/.test(raw)) return 'similar'
  if (/pair|搭配/.test(raw)) return 'pair'
  if (/belongs|category|品类|属于|类型/.test(raw)) return 'category'
  if (/colou?r|颜色|色彩/.test(raw)) return 'color'
  if (/material|fabric|材质|面料/.test(raw)) return 'material'
  if (/style|风格/.test(raw)) return 'style'
  if (/occasion|scene|场景|场合/.test(raw)) return 'occasion'
  if (/size|尺码/.test(raw)) return 'size'
  return 'other'
}

function nodeKind(type?: string): NodeKind {
  const raw = (type || '').toLowerCase()
  if (raw.includes('商品') || /product|item|garment|sku/.test(raw)) return 'product'
  if (raw.includes('品类') || raw.includes('类别') || /categor|type/.test(raw)) return 'category'
  if (raw.includes('颜色') || raw.includes('色彩') || /colou?r/.test(raw)) return 'color'
  if (raw.includes('风格') || /style/.test(raw)) return 'style'
  if (raw.includes('材质') || raw.includes('面料') || /material|fabric/.test(raw)) return 'material'
  if (raw.includes('场景') || raw.includes('场合') || /occasion|scene/.test(raw)) return 'occasion'
  if (raw.includes('属性') || raw.includes('标签') || /attr|tag|size/.test(raw)) return 'attribute'
  return 'other'
}

function metaText(node: KgNode, key: string): string {
  const value = node.meta?.[key]
  return typeof value === 'string' ? value : ''
}

function metaNumber(node: KgNode, key: string): number | null {
  const value = node.meta?.[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function productIdOf(node: KgNode): number | null {
  const metaId = metaNumber(node, 'product_id')
  if (metaId !== null) return metaId
  const match = /^(?:product:|p)(\d+)$/.exec(node.id)
  if (!match) return null
  const parsed = Number(match[1])
  return Number.isFinite(parsed) ? parsed : null
}

function productColor(node: KgNode): string {
  const category = metaText(node, 'category')
  return CATEGORY_COLOR[category] || KIND_COLOR.product
}

function isProduct(node: KgNode): boolean {
  return nodeKind(node.type) === 'product'
}

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function metricLabel(metric?: string): string {
  if (!metric) return '语义余弦 · 切比雪夫视觉'
  const raw = metric.toLowerCase()
  if (raw.includes('cosine')) return '语义余弦 + 切比雪夫视觉'
  if (raw.includes('chebyshev')) return '切比雪夫距离连边'
  return metric
}

function nodeRadius(kind: NodeKind, compact: boolean): number {
  if (kind === 'category') return compact ? 5 : 5.8
  if (kind === 'other' || kind === 'attribute') return compact ? 3.2 : 3.6
  return compact ? 4 : 4.6
}

interface Position {
  x: number
  y: number
  kind: NodeKind
  color: string
  radius: number
}

export function KGGraph({
  nodes,
  edges,
  metric,
  className,
  compact = false,
  showLegend = true,
  onNodeHover,
  onAttributeClick,
}: KGGraphProps) {
  const navigate = useNavigate()
  const rawId = useId()
  const uid = rawId.replace(/[^a-zA-Z0-9_-]/g, '')
  const [hovered, setHovered] = useState<string | null>(null)

  const graph = useMemo(() => {
    const seen = new Set<string>()
    const safeNodes = (nodes ?? []).filter((node) => {
      if (!node || !node.id || seen.has(node.id)) return false
      seen.add(node.id)
      return true
    })
    const products = safeNodes.filter((node) => isProduct(node))
    const others = safeNodes.filter((node) => !isProduct(node))
    const shownProducts = products.slice(0, MAX_PRODUCTS)
    // Keep the graph builder's interleaved order: grouping by kind clusters
    // dozens of same-kind labels into one arc and makes them unreadable.
    const shownOthers = others.slice(0, MAX_OTHERS)
    const shown = [...shownProducts, ...shownOthers]

    const positions = new Map<string, Position>()
    const productRx = compact ? 118 : Math.min(182, 96 + shownProducts.length * 5.6)
    const productRy = compact ? 98 : Math.min(152, 82 + shownProducts.length * 4.0)
    shownProducts.forEach((node, index) => {
      const angle =
        (Math.PI * 2 * index) / Math.max(shownProducts.length, 1) - Math.PI / 2
      positions.set(node.id, {
        x: CX + Math.cos(angle) * productRx,
        y: CY + Math.sin(angle) * productRy,
        kind: 'product',
        color: productColor(node),
        radius: compact ? 22 : 25,
      })
    })

    const outerRx = compact ? 330 : 405
    const outerRy = compact ? 200 : 246
    shownOthers.forEach((node, index) => {
      const step = (Math.PI * 2) / Math.max(shownOthers.length, 1)
      const angle = step * index - Math.PI / 2 + step / 2
      const kind = nodeKind(node.type)
      positions.set(node.id, {
        x: CX + Math.cos(angle) * outerRx,
        y: CY + Math.sin(angle) * outerRy,
        kind,
        color: KIND_COLOR[kind],
        radius: nodeRadius(kind, compact),
      })
    })

    const links = (edges ?? [])
      .filter(
        (edge) =>
          edge &&
          edge.source &&
          edge.target &&
          edge.source !== edge.target &&
          positions.has(edge.source) &&
          positions.has(edge.target),
      )
      .map((edge, index) => {
        const from = positions.get(edge.source)!
        const to = positions.get(edge.target)!
        const dx = to.x - from.x
        const dy = to.y - from.y
        const length = Math.hypot(dx, dy) || 1
        const bend = ((index % 2 === 0 ? 1 : -1) * Math.min(42, length * 0.13))
        const controlX = (from.x + to.x) / 2 - (dy / length) * bend
        const controlY = (from.y + to.y) / 2 + (dx / length) * bend
        const midX = 0.25 * from.x + 0.5 * controlX + 0.25 * to.x
        const midY = 0.25 * from.y + 0.5 * controlY + 0.25 * to.y
        const style = EDGE_STYLE[relationKey(edge.relation)]
        return {
          edge,
          style,
          key: `${edge.source}-${edge.target}-${edge.relation}-${index}`,
          path: `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} Q ${controlX.toFixed(2)} ${controlY.toFixed(2)} ${to.x.toFixed(2)} ${to.y.toFixed(2)}`,
          midX,
          midY,
        }
      })
      .sort(
        (a, b) =>
          a.style.priority - b.style.priority ||
          Math.abs(Number(b.edge.weight) || 0) - Math.abs(Number(a.edge.weight) || 0),
      )
      .slice(0, MAX_EDGES)

    const kinds: NodeKind[] = []
    for (const node of shown) {
      const kind = nodeKind(node.type)
      if (!kinds.includes(kind)) kinds.push(kind)
    }

    const degree = new Map<string, number>()
    for (const link of links) {
      degree.set(link.edge.source, (degree.get(link.edge.source) ?? 0) + 1)
      degree.set(link.edge.target, (degree.get(link.edge.target) ?? 0) + 1)
    }

    return {
      shown,
      positions,
      links,
      kinds,
      degree,
      totalNodes: safeNodes.length,
      totalEdges: (edges ?? []).length,
      productCount: products.length,
      semanticCount: links.filter((link) => link.style.label === '语义相似').length,
    }
  }, [nodes, edges, compact])

  const hoveredNode = graph.shown.find((node) => node.id === hovered) ?? null

  const setHover = (node: KgNode | null) => {
    setHovered(node?.id ?? null)
    onNodeHover?.(node)
  }

  const openProduct = (node: KgNode) => {
    const productId = productIdOf(node)
    if (productId !== null) navigate(`/product/${productId}`)
  }

  if (graph.shown.length === 0) {
    return (
      <div
        className={cn(
          'flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 bg-black/20 px-6 text-center',
          className,
        )}
      >
        <p className="text-sm text-ivory/55">知识图谱尚未建立</p>
        <p className="mt-1.5 max-w-xs text-[10px] leading-5 text-ivory/55">
          NLP 文本模型与视觉小模型完成检索后，会在这里连接商品实拍与语义属性。
        </p>
      </div>
    )
  }

  const connected = new Set<string>()
  if (hovered) {
    for (const link of graph.links) {
      if (link.edge.source === hovered || link.edge.target === hovered) {
        connected.add(link.key)
      }
    }
  }

  return (
    <div className={cn('flex flex-col', className)}>
      <div className="relative flex-1 overflow-hidden rounded-2xl border border-cyan-100/10 bg-[#03070c]">
        <AuroraField />
        <div
          className="pointer-events-none absolute inset-0 z-[1] opacity-60"
          style={{
            background:
              'radial-gradient(ellipse 62% 58% at 50% 48%, transparent 48%, rgba(3,7,12,.52) 100%)',
          }}
        />

        <div className="kg-hud-corner left-3 top-3 z-20 border-l border-t" />
        <div className="kg-hud-corner right-3 top-3 z-20 border-r border-t" />
        <div className="kg-hud-corner bottom-3 left-3 z-20 border-b border-l" />
        <div className="kg-hud-corner bottom-3 right-3 z-20 border-b border-r" />

        <div className="pointer-events-none absolute left-5 top-4 z-20 font-mono text-[9px] uppercase tracking-[0.28em] text-cyan-100/55">
          NLP · FASHION KG
          <span className="ml-2 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#5ef2d6]" />
        </div>
        <div className="pointer-events-none absolute right-5 top-4 z-20 font-mono text-[9px] uppercase tracking-[0.24em] text-cyan-100/35">
          {compact ? 'AURORA // INLINE' : 'AURORA // LIVE'}
        </div>

        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className={cn('relative z-10 w-full', compact ? 'min-h-[220px]' : 'min-h-[360px]')}
          role="img"
          aria-label="服装知识图谱，商品节点使用真实商品图片，语义边以高亮流光显示"
        >
          <defs>
            <filter id={`${uid}-glow`} x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="2.6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id={`${uid}-soft-glow`} x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <radialGradient id={`${uid}-core`}>
              <stop offset="0%" stopColor="#5ef2d6" stopOpacity="0.22" />
              <stop offset="55%" stopColor="#5ef2d6" stopOpacity="0.05" />
              <stop offset="100%" stopColor="#5ef2d6" stopOpacity="0" />
            </radialGradient>
            {(Object.keys(EDGE_STYLE) as RelationKey[]).map((key) => (
              <linearGradient
                key={key}
                id={`${uid}-edge-${key}`}
                x1="0%"
                y1="0%"
                x2="100%"
                y2="0%"
              >
                <stop offset="0%" stopColor={EDGE_STYLE[key].color} stopOpacity="0.03" />
                <stop offset="46%" stopColor={EDGE_STYLE[key].color} stopOpacity="0.92" />
                <stop offset="100%" stopColor={EDGE_STYLE[key].color} stopOpacity="0.14" />
              </linearGradient>
            ))}
            {graph.shown
              .filter((node) => isProduct(node))
              .map((node, index) => {
                const position = graph.positions.get(node.id)
                return position ? (
                  <clipPath key={`${uid}-clip-${node.id}`} id={`${uid}-clip-${index}`}>
                    <circle cx={position.x} cy={position.y} r={position.radius - 2} />
                  </clipPath>
                ) : null
              })}
          </defs>

          <g aria-hidden="true">
            <ellipse
              cx={CX}
              cy={CY}
              rx={compact ? 330 : 405}
              ry={compact ? 200 : 246}
              fill="none"
              stroke="rgba(126,232,220,.11)"
              strokeDasharray="2 8"
            />
            <ellipse
              cx={CX}
              cy={CY}
              rx={compact ? 190 : 250}
              ry={compact ? 132 : 172}
              fill="none"
              stroke="rgba(126,232,220,.08)"
              strokeDasharray="1 7"
            />
            <circle
              cx={CX}
              cy={CY}
              r={compact ? 92 : 116}
              fill={`url(#${uid}-core)`}
            />
            <circle
              cx={CX}
              cy={CY}
              r={compact ? 50 : 58}
              fill="none"
              stroke="rgba(94,242,214,.18)"
              strokeDasharray="2 6"
            />
            <circle
              cx={CX}
              cy={CY}
              r={compact ? 64 : 76}
              fill="none"
              stroke="rgba(216,190,147,.13)"
              strokeDasharray="1 9"
            />
            <g className="kg-orbit" style={{ transformOrigin: `${CX}px ${CY}px` }}>
              <path
                d={`M ${CX - 76} ${CY} A 76 76 0 0 1 ${CX} ${CY - 76}`}
                fill="none"
                stroke="rgba(94,242,214,.52)"
                strokeWidth="1.2"
                strokeLinecap="round"
              />
              <path
                d={`M ${CX + 76} ${CY} A 76 76 0 0 1 ${CX} ${CY + 76}`}
                fill="none"
                stroke="rgba(216,190,147,.4)"
                strokeWidth="1"
                strokeLinecap="round"
              />
            </g>
          </g>

          <g aria-hidden="true">
            {graph.links.map((link, index) => {
              const isConnected = connected.has(link.key)
              const dimmed = hovered !== null && !isConnected
              const opacity = dimmed ? 0.1 : isConnected ? 1 : 0.64
              const width = link.style.width + Math.min(Math.abs(link.edge.weight) || 0, 1.5) * 0.6
              return (
                <g key={link.key}>
                  <path
                    d={link.path}
                    fill="none"
                    stroke={`url(#${uid}-edge-${relationKey(link.edge.relation)})`}
                    strokeWidth={width}
                    strokeLinecap="round"
                    opacity={opacity}
                    filter={link.style.glow ? `url(#${uid}-glow)` : undefined}
                    className={link.style.flow ? 'kg-edge-flow' : 'kg-edge-thin'}
                    style={{ transition: 'opacity 180ms ease' }}
                  />
                  {link.style.label === '语义相似' && index < 18 ? (
                    <circle r={2.1} fill="#d7fff8" opacity={dimmed ? 0.08 : 0.86}>
                      <animateMotion
                        dur={`${3.2 + (index % 4) * 0.9}s`}
                        repeatCount="indefinite"
                        path={link.path}
                      />
                    </circle>
                  ) : null}
                  {hovered && isConnected && !compact ? (
                    <g pointerEvents="none">
                      <rect
                        x={link.midX - (link.style.label.length * 5.2 + 7)}
                        y={link.midY - 9}
                        width={link.style.label.length * 10.4 + 14}
                        height={17}
                        rx={8.5}
                        fill="rgba(3,7,12,.78)"
                        stroke={link.style.color}
                        strokeOpacity={0.28}
                      />
                      <text
                        x={link.midX}
                        y={link.midY + 3.6}
                        textAnchor="middle"
                        fontSize={8.6}
                        letterSpacing="0.08em"
                        fill={link.style.color}
                      >
                        {link.style.label}
                      </text>
                    </g>
                  ) : null}
                </g>
              )
            })}
          </g>

          <g aria-hidden="true" pointerEvents="none">
            <text
              x={CX}
              y={CY - 5}
              textAnchor="middle"
              fontSize={compact ? 13 : 16}
              fontFamily="Georgia, 'Times New Roman', 'Songti SC', serif"
              fill="rgba(214,255,246,.72)"
              letterSpacing="0.24em"
            >
              衣见
            </text>
            <text
              x={CX}
              y={CY + 13}
              textAnchor="middle"
              fontSize={compact ? 5.4 : 6.2}
              fontFamily="'Cascadia Code', Consolas, monospace"
              fill="rgba(126,232,220,.42)"
              letterSpacing="0.32em"
            >
              NLP CORE
            </text>
          </g>

          {graph.shown.map((node) => {
            const position = graph.positions.get(node.id)
            if (!position) return null
            const product = position.kind === 'product'
            const isHovered = node.id === hovered
            const label = node.label || node.id
            if (!product) {
              const anchor: 'start' | 'end' | 'middle' =
                Math.abs(position.x - CX) < 18
                  ? 'middle'
                  : position.x < CX
                    ? 'end'
                    : 'start'
              const labelX =
                position.x + (anchor === 'end' ? -8 : anchor === 'start' ? 8 : 0)
              const labelY =
                anchor === 'middle'
                  ? position.y + (position.y < CY ? -9 : 13)
                  : position.y + 3
              return (
                <g
                  key={node.id}
                  className="cursor-pointer"
                  onMouseEnter={() => setHover(node)}
                  onMouseLeave={() => setHover(null)}
                  onClick={(event) => {
                    event.stopPropagation()
                    setHover(node)
                    onAttributeClick?.(node)
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={`属性节点 ${label}`}
                  onFocus={() => setHover(node)}
                  onBlur={() => setHover(null)}
                >
                  <circle
                    cx={position.x}
                    cy={position.y}
                    r={Math.max(12, position.radius + 7)}
                    fill="rgba(0,0,0,0)"
                    style={{ pointerEvents: 'all' }}
                  />
                  <path
                    d={`M ${position.x} ${position.y - position.radius} L ${position.x + position.radius} ${position.y} L ${position.x} ${position.y + position.radius} L ${position.x - position.radius} ${position.y} Z`}
                    fill={position.color}
                    fillOpacity={isHovered ? 1 : 0.72}
                    stroke="rgba(3,7,12,.85)"
                    strokeWidth={1.2}
                    filter={isHovered ? `url(#${uid}-soft-glow)` : undefined}
                  />
                  {position.kind === 'category' || isHovered || compact || (graph.degree.get(node.id) ?? 0) >= 6 ? (
                    <text
                      x={labelX}
                      y={labelY}
                      textAnchor={anchor}
                      fontSize={position.kind === 'category' ? 9.4 : 8.2}
                      fill={isHovered ? 'rgba(245,239,230,.96)' : 'rgba(220,245,240,.58)'}
                      style={{ pointerEvents: 'none' }}
                    >
                      {clip(label, position.kind === 'category' ? 10 : 8)}
                    </text>
                  ) : null}
                  <title>
                    {label} · {KIND_LABEL[position.kind]}
                  </title>
                </g>
              )
            }

            const productIndex = graph.shown.filter((item) => isProduct(item)).findIndex((item) => item.id === node.id)
            const image = metaText(node, 'image')
            const price = metaNumber(node, 'price')
            const radius = position.radius
            return (
              <g
                key={node.id}
                className="cursor-pointer"
                onMouseEnter={() => setHover(node)}
                onMouseLeave={() => setHover(null)}
                onClick={(event) => {
                  event.stopPropagation()
                  openProduct(node)
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    openProduct(node)
                  }
                }}
                tabIndex={0}
                role="link"
                aria-label={`${label}，点击进入商品详情`}
                onFocus={() => setHover(node)}
                onBlur={() => setHover(null)}
              >
                <circle
                  cx={position.x}
                  cy={position.y}
                  r={radius + 13}
                  fill={position.color}
                  fillOpacity={isHovered ? 0.16 : 0.07}
                  filter={`url(#${uid}-soft-glow)`}
                  className="kg-node-halo"
                />
                <circle
                  cx={position.x}
                  cy={position.y}
                  r={radius + 6}
                  fill="none"
                  stroke={position.color}
                  strokeOpacity={isHovered ? 0.95 : 0.42}
                  strokeWidth={isHovered ? 1.7 : 1}
                  strokeDasharray="2 6"
                  className="kg-orbit"
                />
                <circle
                  cx={position.x}
                  cy={position.y}
                  r={radius}
                  fill="#081018"
                  stroke={position.color}
                  strokeWidth={isHovered ? 2 : 1.4}
                  strokeOpacity={0.9}
                />
                {image ? (
                  <image
                    href={image}
                    x={position.x - radius + 2}
                    y={position.y - radius + 2}
                    width={(radius - 2) * 2}
                    height={(radius - 2) * 2}
                    preserveAspectRatio="xMidYMid slice"
                    clipPath={`url(#${uid}-clip-${productIndex})`}
                    style={{ pointerEvents: 'none' }}
                  />
                ) : (
                  <text
                    x={position.x}
                    y={position.y + 4}
                    textAnchor="middle"
                    fontSize={radius * 0.8}
                    fill={position.color}
                    style={{ pointerEvents: 'none' }}
                  >
                    {label.slice(0, 1)}
                  </text>
                )}
                <circle
                  cx={position.x}
                  cy={position.y}
                  r={radius}
                  fill="none"
                  stroke={position.color}
                  strokeOpacity={isHovered ? 1 : 0.75}
                  strokeWidth={isHovered ? 1.6 : 1.1}
                  style={{ pointerEvents: 'none' }}
                />
                {isHovered && price !== null ? (
                  <g pointerEvents="none">
                    <rect
                      x={position.x - 27}
                      y={position.y - radius - 29}
                      width={54}
                      height={17}
                      rx={8.5}
                      fill="rgba(3,7,12,.82)"
                      stroke={position.color}
                      strokeOpacity={0.4}
                    />
                    <text
                      x={position.x}
                      y={position.y - radius - 17.2}
                      textAnchor="middle"
                      fontSize={8.4}
                      fill="#e9fff9"
                    >
                      ¥{price.toFixed(0)}
                    </text>
                  </g>
                ) : null}
                <text
                  x={position.x}
                  y={position.y + radius + (compact ? 13 : 16)}
                  textAnchor="middle"
                  fontSize={compact ? 8.6 : 10.2}
                  fill={isHovered ? 'rgba(245,255,252,.98)' : 'rgba(235,248,244,.82)'}
                  stroke="rgba(3,7,12,.72)"
                  strokeWidth={2.4}
                  paintOrder="stroke"
                  style={{ pointerEvents: 'none' }}
                >
                  {clip(label, compact ? 8 : 11)}
                </text>
                <title>
                  {label} · {metaText(node, 'category') || '商品'} · 点击进入商品详情
                </title>
              </g>
            )
          })}
        </svg>
      </div>

      {showLegend ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[9px] text-ivory/55">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {graph.kinds.map((kind) => (
              <span key={kind} className="inline-flex items-center gap-1">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: KIND_COLOR[kind] }}
                />
                {KIND_LABEL[kind]}
              </span>
            ))}
            <span className="inline-flex items-center gap-1 text-cyan-100/70">
              <span className="h-px w-4 bg-[#5ef2d6]" />
              语义相似
            </span>
          </div>
          <span>
            {graph.shown.length < graph.totalNodes
              ? `显示 ${graph.shown.length} / ${graph.totalNodes} 个节点`
              : `${graph.totalNodes} 个节点`}{' '}
            · {graph.links.length} / {graph.totalEdges} 条关系
          </span>
        </div>
      ) : null}
      <p className="mt-1 text-[9px] tracking-[0.14em] text-ivory/55">
        {graph.links.some((link) => link.style.label === '语义相似')
          ? '语义余弦 + 切比雪夫视觉'
          : metricLabel(metric)}{' '}
        · 商品实拍节点 · 点击图片进入商品页
      </p>
    </div>
  )
}

export type KgRelationKey = RelationKey

export const KG_RELATION_OPTIONS: Array<{
  key: KgRelationKey
  label: string
  color: string
}> = (Object.keys(EDGE_STYLE) as RelationKey[]).map((key) => ({
  key,
  label: EDGE_STYLE[key].label,
  color: EDGE_STYLE[key].color,
}))

export function kgRelationKey(relation?: string): KgRelationKey {
  return relationKey(relation)
}

export function kgProductId(node: KgNode): number | null {
  return productIdOf(node)
}

export default KGGraph
