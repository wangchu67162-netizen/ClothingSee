import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  ChevronLeft,
  ChevronRight,
  ScanSearch,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react'
import { ImageSearchDialog, ProductGrid } from '@/components/product'
import { GlassButton, GlassInput } from '@/components/ui'
import { api, apiErrorMessage } from '@/lib/api'
import type { Category, ImageSearchResult, ProductList } from '@/types'
import { cn } from '@/lib/cn'

const SORTS = [
  { value: 'new', label: '最新上架' },
  { value: 'sales', label: '人气优先' },
  { value: 'price_asc', label: '价格从低到高' },
  { value: 'price_desc', label: '价格从高到低' },
]

export function Shop() {
  const [data, setData] = useState<ProductList | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('new')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [imageOpen, setImageOpen] = useState(false)
  const [imageResult, setImageResult] = useState<ImageSearchResult | null>(null)
  const imageSectionRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    let alive = true
    api
      .get<Category[]>('/products/categories', { auth: false })
      .then((value) => {
        if (alive) setCategories(value)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ page: String(page), page_size: '12', sort })
    if (query) params.set('q', query)
    if (category) params.set('category', category)
    api
      .get<ProductList>(`/products?${params.toString()}`, { auth: false })
      .then((value) => {
        if (!alive) return
        setData(value)
        setLoading(false)
      })
      .catch((reason) => {
        if (!alive) return
        setError(apiErrorMessage(reason))
        setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [query, category, sort, page, reloadKey])

  useEffect(() => {
    if (!imageResult) return
    const node = imageSectionRef.current
    if (!node) return
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    node.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  }, [imageResult])

  const visionSummary = useMemo(() => {
    const vision = imageResult?.vision
    if (!vision) return ''
    if (typeof vision.summary === 'string' && vision.summary) return vision.summary
    const parts: string[] = []
    if (typeof vision.category === 'string' && vision.category) parts.push(`品类：${vision.category}`)
    if (Array.isArray(vision.colors)) {
      const colors = vision.colors.filter((item): item is string => typeof item === 'string')
      if (colors.length) parts.push(`主色：${colors.join('、')}`)
    }
    return parts.join(' · ')
  }, [imageResult])

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    setPage(1)
    setQuery(draft.trim())
  }

  const resetFilters = () => {
    setQuery('')
    setDraft('')
    setCategory('')
    setPage(1)
  }

  const pages = useMemo(() => {
    if (!data) return []
    const total = Math.min(data.pages, 7)
    const start = Math.max(1, Math.min(data.page - 2, data.pages - total + 1))
    return Array.from({ length: total }, (_, index) => start + index)
  }, [data])

  return (
    <div className="page-pad mx-auto max-w-[1440px]">
      <div className="flex flex-col gap-6 pb-8 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="eyebrow mb-3">THE WARDROBE · 2026 AW</p>
          <h1 className="display text-[clamp(2.8rem,5.4vw,5.4rem)] leading-none text-ivory">本季衣橱</h1>
          <p className="mt-4 max-w-md text-sm leading-7 text-ivory/55">
            由视觉小模型与知识图谱共同整理。每一件的面料、廓形与场合，都被认真对待。
          </p>
        </div>
        <Link
          to="/stylist"
          className="group flex items-center gap-2 text-xs tracking-[0.14em] text-champagne/90 transition hover:text-champagne"
        >
          <Sparkles className="h-3.5 w-3.5" />
          不知道选哪件？让五位智能体替你看看
          <ChevronRight className="h-3.5 w-3.5 transition group-hover:translate-x-1" />
        </Link>
      </div>

      <div className="glass mb-7 rounded-[24px] p-3 md:p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <form onSubmit={onSubmit} className="relative flex-1" role="search" aria-label="商品搜索">
            <GlassInput
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="搜索风衣、真丝衬衫、新中式……"
              icon={<Search className="h-4 w-4" />}
              className="h-11 rounded-full pr-24"
              aria-label="搜索商品"
            />
            <button
              type="submit"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-full bg-champagne/90 px-4 py-2 text-[11px] font-medium text-ink-950 transition hover:bg-champagne"
            >
              搜索
            </button>
          </form>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setImageOpen(true)}
              className="btn-glass h-10 flex-1 gap-2 rounded-full border-champagne/30 bg-champagne/8 px-4 text-[11px] tracking-[0.12em] text-champagne sm:flex-none"
            >
              <ScanSearch className="h-4 w-4" /> 以图搜衣
            </button>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-ivory/55">
                <SlidersHorizontal className="h-3.5 w-3.5" /> 排序
              </span>
              <select
                value={sort}
                onChange={(event) => {
                  setPage(1)
                  setSort(event.target.value)
                }}
                className="input-glass h-10 w-auto rounded-full py-0 pr-8 text-xs"
                aria-label="排序方式"
              >
                {SORTS.map((item) => (
                  <option key={item.value} value={item.value} className="bg-ink-900">
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setCategory('')
              setPage(1)
            }}
            aria-pressed={!category}
            className={cn(
              'rounded-full border px-3.5 py-1.5 text-[11px] tracking-[0.1em] transition',
              !category
                ? 'border-champagne/50 bg-champagne/12 text-champagne'
                : 'border-white/10 text-ivory/55 hover:border-white/20 hover:text-ivory/75',
            )}
          >
            全部
          </button>
          {categories.map((item) => (
            <button
              key={item.name}
              type="button"
              onClick={() => {
                setCategory(item.name)
                setPage(1)
              }}
              aria-pressed={category === item.name}
              className={cn(
                'rounded-full border px-3.5 py-1.5 text-[11px] tracking-[0.1em] transition',
                category === item.name
                  ? 'border-champagne/50 bg-champagne/12 text-champagne'
                  : 'border-white/10 text-ivory/55 hover:border-white/20 hover:text-ivory/75',
              )}
            >
              {item.name}
              <span className="ml-1.5 text-ivory/55">{item.count}</span>
            </button>
          ))}
          {(query || category) && (
            <button
              type="button"
              onClick={resetFilters}
              className="ml-1 flex items-center gap-1 rounded-full px-2 py-1.5 text-[11px] text-ivory/55 transition hover:text-ember"
            >
              <X className="h-3 w-3" /> 清除筛选
            </button>
          )}
        </div>
      </div>

      {imageResult && (
        <section
          ref={imageSectionRef}
          aria-labelledby="vision-search-heading"
          className="mb-12 scroll-mt-28"
        >
          <div className="glass rounded-[24px] p-5 md:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="eyebrow mb-2">
                  VISION SEARCH · {String(imageResult.backend || 'stub').toUpperCase()}
                </p>
                <h2 id="vision-search-heading" className="display text-3xl text-ivory md:text-4xl">
                  以图搜衣
                </h2>
                <p className="mt-2 text-xs leading-6 text-ivory/55" aria-live="polite">
                  {imageResult.items.length > 0
                    ? `以${imageResult.distance_metric === 'chebyshev' ? '切比雪夫距离' : imageResult.distance_metric || '视觉向量'}找出 ${imageResult.items.length} 件相近作品。`
                    : '没有找到足够相似的作品，换一张更清晰的图片试试。'}
                </p>
                {visionSummary && (
                  <p className="mt-2 text-xs leading-6 text-ivory/55">视觉解析：{visionSummary}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setImageResult(null)}
                className="flex items-center gap-1.5 rounded-full border border-white/12 px-3 py-1.5 text-[11px] text-ivory/55 transition hover:border-white/25 hover:text-ivory"
              >
                <X className="h-3.5 w-3.5" /> 清除结果
              </button>
            </div>
            {imageResult.items.length > 0 && (
              <ProductGrid products={imageResult.items} className="mt-6" />
            )}
          </div>
        </section>
      )}

      {loading ? (
        <>
          <div className="mb-4 flex items-center justify-between text-[10px] uppercase tracking-[0.18em] text-ivory/55">
            <span>正在整理衣架…</span>
            <span>第 {page} 页</span>
          </div>
          <ProductGrid products={[]} loading skeletonCount={8} />
        </>
      ) : error ? (
        <div className="glass rounded-3xl px-6 py-16 text-center" role="alert">
          <p className="display text-3xl text-ivory/80">衣架暂时没有打开</p>
          <p className="mt-3 text-sm text-ember">{error}</p>
          <GlassButton variant="primary" className="mt-5" onClick={() => setReloadKey((value) => value + 1)}>
            重新加载
          </GlassButton>
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="glass rounded-3xl px-6 py-20 text-center">
          <p className="display text-3xl text-ivory/80">没有找到合适的衣裳</p>
          <p className="mt-3 text-sm text-ivory/55">试试更宽泛的词，或者让 AI 造型师看看你的照片。</p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <GlassButton onClick={resetFilters}>清除筛选</GlassButton>
            <Link to="/stylist">
              <GlassButton variant="primary">前往 AI 造型室</GlassButton>
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div
            className="mb-4 flex flex-wrap items-center justify-between gap-2 text-[10px] uppercase tracking-[0.18em] text-ivory/55"
            aria-live="polite"
          >
            <span>
              {data.total} 件作品{query ? ` · “${query}”` : ''}
            </span>
            <span>
              第 {data.page} / {data.pages || 1} 页
            </span>
          </div>
          <ProductGrid products={data.items} />
          {data.pages > 1 && (
            <div className="mt-12 flex items-center justify-center gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                className="btn-glass h-9 w-9 p-0 disabled:opacity-30"
                aria-label="上一页"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              {pages.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setPage(item)}
                  aria-label={`第 ${item} 页`}
                  aria-current={item === data.page ? 'page' : undefined}
                  className={cn(
                    'h-9 min-w-9 rounded-full px-2 text-xs transition',
                    item === data.page
                      ? 'bg-champagne text-ink-950'
                      : 'text-ivory/55 hover:bg-white/8 hover:text-ivory',
                  )}
                >
                  {item}
                </button>
              ))}
              <button
                type="button"
                disabled={page >= data.pages}
                onClick={() => setPage((value) => Math.min(data.pages, value + 1))}
                className="btn-glass h-9 w-9 p-0 disabled:opacity-30"
                aria-label="下一页"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </>
      )}

      <ImageSearchDialog
        open={imageOpen}
        onClose={() => setImageOpen(false)}
        onResults={(result) => setImageResult(result)}
      />
    </div>
  )
}

export default Shop
