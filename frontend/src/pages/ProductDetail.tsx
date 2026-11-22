import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Check,
  Minus,
  Plus,
  RotateCcw,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Truck,
} from 'lucide-react'
import type { Product, ProductList } from '@/types'
import { api, apiErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { useCartStore } from '@/store/cart'
import { useToast } from '@/store/toast'
import { GlassButton, GlassPanel, PriceTag } from '@/components/ui'
import { ProductGallery, ProductGrid } from '@/components/product'
import { formatPrice } from '@/lib/format'
import { cn } from '@/lib/cn'

const COMFORT_LABELS: Record<string, string> = {
  breathability: '透气',
  warmth: '保暖',
  softness: '柔软',
  stretch: '弹性',
  weight: '重量',
  care: '护理',
}

export function ProductDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const add = useCartStore((state) => state.add)
  const toast = useToast()
  const [product, setProduct] = useState<Product | null>(null)
  const [related, setRelated] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [size, setSize] = useState('')
  const [color, setColor] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    if (!id) return
    let alive = true
    setLoading(true)
    setError(null)
    setProduct(null)
    setRelated([])
    setQuantity(1)
    api
      .get<Product>(`/products/${id}`, { auth: false })
      .then((value) => {
        if (!alive) return
        setProduct(value)
        setSize(value.sizes[0] ?? '均码')
        setColor(value.colors[0] ?? '默认色')
        setLoading(false)
        return api
          .get<ProductList>(
            `/products?category=${encodeURIComponent(value.category)}&page_size=5&sort=sales`,
            { auth: false },
          )
          .then((list) => {
            if (alive) {
              setRelated(list.items.filter((item) => String(item.id) !== id).slice(0, 4))
            }
          })
          .catch(() => undefined)
      })
      .catch((reason) => {
        if (!alive) return
        setError(apiErrorMessage(reason))
        setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [id])

  if (loading) {
    return (
      <div className="page-pad mx-auto max-w-[1320px]" aria-busy="true" aria-label="正在加载商品详情">
        <div className="mb-6 h-3 w-24 animate-pulse rounded-full bg-white/[0.05] motion-reduce:animate-none" />
        <div className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-14">
          <div>
            <div className="aspect-[3/4] animate-pulse rounded-[30px] border border-white/8 bg-white/[0.04] motion-reduce:animate-none" />
            <div className="mt-3 grid grid-cols-4 gap-2.5">
              {Array.from({ length: 3 }, (_, index) => (
                <div
                  key={index}
                  className="aspect-square animate-pulse rounded-2xl border border-white/8 bg-white/[0.03] motion-reduce:animate-none"
                />
              ))}
            </div>
          </div>
          <div className="space-y-4 pt-2">
            <div className="h-3 w-28 animate-pulse rounded-full bg-white/[0.05] motion-reduce:animate-none" />
            <div className="h-14 w-3/4 animate-pulse rounded-2xl bg-white/[0.05] motion-reduce:animate-none" />
            <div className="h-4 w-2/3 animate-pulse rounded-full bg-white/[0.04] motion-reduce:animate-none" />
            <div className="h-9 w-1/3 animate-pulse rounded-full bg-white/[0.05] motion-reduce:animate-none" />
            <div className="h-px w-full bg-white/8" />
            <div className="h-4 w-1/2 animate-pulse rounded-full bg-white/[0.04] motion-reduce:animate-none" />
            <div className="h-11 w-full animate-pulse rounded-full bg-white/[0.05] motion-reduce:animate-none" />
          </div>
        </div>
      </div>
    )
  }

  if (error || !product) {
    return (
      <div className="page-pad mx-auto max-w-3xl py-24 text-center">
        <p className="display text-4xl text-ivory">这件衣裳暂时不在架上</p>
        <p className="mt-3 text-sm text-ivory/55">{error || '商品不存在'}</p>
        <div className="mt-7 flex justify-center gap-3">
          <Link to="/shop">
            <GlassButton variant="primary">回到衣橱</GlassButton>
          </Link>
          <GlassButton onClick={() => window.history.back()}>返回上一页</GlassButton>
        </div>
      </div>
    )
  }

  const gallery = product.gallery?.length ? product.gallery : [product.image]
  const colors = product.colors.length > 0 ? product.colors : ['默认色']
  const sizes = product.sizes.length > 0 ? product.sizes : ['均码']
  const stock = Math.max(0, product.stock)
  const soldOut = stock <= 0
  const lowStock = !soldOut && stock <= 10
  const maxQuantity = soldOut ? 1 : Math.max(1, Math.min(20, stock))
  const discount =
    product.original_price && product.original_price > product.price
      ? Math.round((1 - product.price / product.original_price) * 100)
      : 0

  const handleAdd = async (buyNow = false) => {
    if (soldOut) {
      toast.info('暂时售罄', `${product.name} 正在补货，可以先看看同品类的其他作品。`)
      return
    }
    if (!user) {
      navigate(`/auth?next=${encodeURIComponent(`/product/${id}`)}`)
      return
    }
    setAdding(true)
    const safeQuantity = Math.max(1, Math.min(quantity, maxQuantity))
    try {
      await add(product.id, { quantity: safeQuantity, size, color })
      toast.success(
        '已放入购物袋',
        `${product.name} · ${size || '均码'} · ${color || '默认色'} × ${safeQuantity}`,
      )
      if (buyNow) navigate('/checkout')
    } catch (reason) {
      toast.error('加入失败', apiErrorMessage(reason))
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="page-pad mx-auto max-w-[1320px]">
      <Link
        to="/shop"
        className="mb-6 inline-flex items-center gap-2 text-xs tracking-[0.12em] text-ivory/55 transition hover:text-champagne"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 返回衣橱
      </Link>

      <div className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-14">
        <ProductGallery
          key={product.id}
          images={gallery}
          name={product.name}
          badge={
            <span className="rounded-full border border-white/15 bg-black/35 px-3 py-1.5 text-[10px] tracking-[0.18em] text-ivory/65 backdrop-blur-md">
              {product.category}
            </span>
          }
        />

        <div className="lg:sticky lg:top-28 lg:self-start">
          <p className="eyebrow mb-3">
            {product.sku.toUpperCase()} · {product.season || 'ATELIER'}
          </p>
          <h1 className="display text-[clamp(2.4rem,4vw,4.2rem)] leading-[1.02] text-ivory">
            {product.name}
          </h1>
          <p className="mt-3 text-sm leading-7 text-ivory/55">{product.subtitle}</p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <PriceTag price={product.price} originalPrice={product.original_price} size="lg" />
            {discount > 0 && (
              <span className="rounded-full border border-ember/30 bg-ember/8 px-2.5 py-1 text-[10px] tracking-[0.16em] text-ember/90">
                -{discount}%
              </span>
            )}
            <span className="text-[11px] text-ivory/55">
              已售 {product.sales} · 评分 {product.rating.toFixed(1)}
            </span>
          </div>
          {discount > 0 && product.original_price && (
            <p className="mt-2 text-[11px] text-champagne/85">
              限时优惠 · 立省 {formatPrice(product.original_price - product.price)}
            </p>
          )}

          <p
            className={cn(
              'mt-4 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px]',
              soldOut
                ? 'border-ember/30 bg-ember/8 text-ember'
                : lowStock
                  ? 'border-champagne/30 bg-champagne/8 text-champagne'
                  : 'border-sage/25 bg-sage/8 text-sage',
            )}
          >
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                soldOut ? 'bg-ember' : lowStock ? 'bg-champagne' : 'bg-sage',
              )}
            />
            {soldOut ? '暂时售罄，正在补货' : lowStock ? `仅剩 ${stock} 件，欲购从速` : `现货 ${stock} 件`}
          </p>

          <div className="my-7 hairline" />

          <div className="space-y-5">
            <div>
              <p className="mb-2.5 text-[10px] uppercase tracking-[0.24em] text-ivory/55">
                颜色 · {color}
              </p>
              <div className="flex flex-wrap gap-2">
                {colors.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setColor(item)}
                    aria-pressed={color === item}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-xs transition',
                      color === item
                        ? 'border-champagne/60 bg-champagne/10 text-champagne'
                        : 'border-white/12 text-ivory/55 hover:border-white/25',
                    )}
                  >
                    {color === item && <Check className="h-3 w-3" />}
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2.5 text-[10px] uppercase tracking-[0.24em] text-ivory/55">
                尺码 · {size}
              </p>
              <div className="flex flex-wrap gap-2">
                {sizes.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setSize(item)}
                    aria-pressed={size === item}
                    className={cn(
                      'min-w-12 rounded-full border px-4 py-2 text-xs transition',
                      size === item
                        ? 'border-champagne/60 bg-champagne/10 text-champagne'
                        : 'border-white/12 text-ivory/55 hover:border-white/25',
                    )}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="mb-2.5 text-[10px] uppercase tracking-[0.24em] text-ivory/55">数量</p>
                <div className="inline-flex items-center rounded-full border border-white/12">
                  <button
                    type="button"
                    onClick={() => setQuantity((value) => Math.max(1, value - 1))}
                    disabled={quantity <= 1 || soldOut}
                    className="p-2.5 text-ivory/55 transition hover:text-ivory disabled:opacity-30"
                    aria-label="减少数量"
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </button>
                  <span className="min-w-9 text-center text-sm text-ivory" aria-live="polite">
                    {quantity}
                  </span>
                  <button
                    type="button"
                    onClick={() => setQuantity((value) => Math.min(maxQuantity, value + 1))}
                    disabled={quantity >= maxQuantity || soldOut}
                    className="p-2.5 text-ivory/55 transition hover:text-ivory disabled:opacity-30"
                    aria-label="增加数量"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              {!soldOut && (
                <p className="text-[10px] tracking-[0.08em] text-ivory/55">
                  单次最多 {maxQuantity} 件
                </p>
              )}
            </div>
          </div>

          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <GlassButton
              variant="primary"
              size="lg"
              loading={adding}
              disabled={soldOut}
              className="flex-1"
              icon={<ShoppingBag className="h-4 w-4" />}
              onClick={() => handleAdd(false)}
            >
              {soldOut ? '暂时售罄' : '放入购物袋'}
            </GlassButton>
            <GlassButton
              variant="glass"
              size="lg"
              loading={adding}
              disabled={soldOut}
              className="flex-1"
              icon={<Sparkles className="h-4 w-4" />}
              onClick={() => handleAdd(true)}
            >
              {soldOut ? '等待补货' : '立即购买'}
            </GlassButton>
          </div>

          <div className="mt-6 grid grid-cols-3 gap-2 text-center">
            {[
              [Truck, '模拟配送', '演示站点'],
              [RotateCcw, '7 天退换', '演示政策'],
              [ShieldCheck, '正品保障', '课程演示'],
            ].map(([Icon, title, hint]) => {
              const Component = Icon as typeof Truck
              return (
                <div
                  key={String(title)}
                  className="rounded-2xl border border-white/8 bg-white/[0.025] px-2 py-3"
                >
                  <Component className="mx-auto h-4 w-4 text-champagne/65" />
                  <p className="mt-1.5 text-[10px] text-ivory/55">{String(title)}</p>
                  <p className="text-[9px] text-ivory/55">{String(hint)}</p>
                </div>
              )
            })}
          </div>

          <GlassPanel className="mt-6 rounded-2xl p-5">
            <p className="eyebrow mb-3">DESIGN NOTES</p>
            <p className="text-sm leading-7 text-ivory/55">{product.description}</p>
            <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-ivory/55">面料</p>
                <p className="mt-0.5 text-ivory/65">{product.fabric}</p>
              </div>
              <div>
                <p className="text-ivory/55">版型</p>
                <p className="mt-0.5 text-ivory/65">{product.fit}</p>
              </div>
              <div>
                <p className="text-ivory/55">场合</p>
                <p className="mt-0.5 text-ivory/65">{product.occasion || '日常'}</p>
              </div>
              <div>
                <p className="text-ivory/55">季节</p>
                <p className="mt-0.5 text-ivory/65">{product.season || '四季'}</p>
              </div>
            </div>
            {product.style_tags.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {product.style_tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[10px] text-ivory/55"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {product.comfort && Object.keys(product.comfort).length > 0 && (
              <div className="mt-5 flex flex-wrap gap-2">
                {Object.entries(product.comfort).map(([key, value]) => (
                  <span
                    key={key}
                    className="rounded-full border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[10px] text-ivory/55"
                  >
                    {COMFORT_LABELS[key] ?? key} · {String(value)}
                  </span>
                ))}
              </div>
            )}
          </GlassPanel>
        </div>
      </div>

      {related.length > 0 && (
        <section className="mt-20">
          <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow mb-2">MORE TO EXPLORE</p>
              <h2 className="display text-3xl text-ivory">同品类 · 更多选择</h2>
            </div>
            <Link to="/shop" className="text-xs text-ivory/55 transition hover:text-champagne">
              更多同类
            </Link>
          </div>
          <ProductGrid products={related} />
        </section>
      )}
    </div>
  )
}

export default ProductDetail
