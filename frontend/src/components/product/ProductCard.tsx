import type { MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Plus, Star } from 'lucide-react'
import type { Product } from '@/types'
import { ImageWithFallback, PriceTag } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import { useCartStore } from '@/store/cart'
import { useToast } from '@/store/toast'
import { apiErrorMessage } from '@/lib/api'
import { cn } from '@/lib/cn'

interface ProductCardProps {
  product: Product
  onAdd?: (product: Product) => void
  className?: string
  priority?: boolean
}

/**
 * 商品卡片。props 契约保持 {product,onAdd?,className?,priority?} 不变，T8 可直接复用。
 */
export function ProductCard({ product, onAdd, className, priority = false }: ProductCardProps) {
  const user = useAuthStore((state) => state.user)
  const add = useCartStore((state) => state.add)
  const navigate = useNavigate()
  const toast = useToast()

  const stock = Number.isFinite(product.stock) ? product.stock : 0
  const soldOut = stock <= 0
  const lowStock = !soldOut && stock <= 10
  const discount =
    product.original_price && product.original_price > product.price
      ? Math.round((1 - product.price / product.original_price) * 100)
      : 0
  const similarityPercent =
    product.similarity !== null && product.similarity !== undefined && Number.isFinite(product.similarity)
      ? Math.round(product.similarity <= 1 ? product.similarity * 100 : product.similarity)
      : null

  const handleAdd = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    if (soldOut) {
      toast.info('暂时售罄', `${product.name} 正在补货，去看看同品类其他作品吧。`)
      return
    }
    if (onAdd) {
      onAdd(product)
      return
    }
    if (!user) {
      navigate(`/auth?next=${encodeURIComponent(`/product/${product.id}`)}`)
      return
    }
    try {
      await add(product.id, {
        quantity: 1,
        size: product.sizes[0] ?? '',
        color: product.colors[0] ?? '',
      })
      toast.success('已放入购物袋', product.name)
    } catch (error) {
      toast.error('加入失败', apiErrorMessage(error))
    }
  }

  return (
    <article className={cn('group relative flex flex-col', className)}>
      <div className="relative overflow-hidden rounded-[22px] border border-white/10 bg-ink-800">
        <Link
          to={`/product/${product.id}`}
          aria-label={`查看 ${product.name}`}
          className="block rounded-[22px] focus-visible:outline-offset-[-4px]"
        >
          <div className="aspect-[3/4] overflow-hidden">
            <ImageWithFallback
              src={product.image}
              alt={product.name}
              loading={priority ? 'eager' : 'lazy'}
              className="h-full w-full object-cover transition duration-700 ease-out group-hover:scale-[1.045]"
            />
          </div>
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
        </Link>

        <button
          type="button"
          onClick={handleAdd}
          disabled={soldOut}
          className={cn(
            'absolute bottom-3 right-3 flex h-10 w-10 items-center justify-center rounded-full border border-white/20 bg-black/35 text-ivory backdrop-blur-xl transition duration-300',
            soldOut
              ? 'cursor-not-allowed border-white/10 text-ivory/55'
              : 'opacity-0 hover:border-champagne/60 hover:text-champagne group-hover:opacity-100 max-md:opacity-100',
          )}
          aria-label={soldOut ? `${product.name} 暂时售罄` : `把 ${product.name} 加入购物袋`}
        >
          {soldOut ? <span className="text-[9px] tracking-[0.08em]">售罄</span> : <Plus className="h-4 w-4" />}
        </button>

        <div className="absolute left-3 top-3 flex flex-col items-start gap-1.5">
          {product.featured && (
            <span className="rounded-full border border-champagne/35 bg-black/35 px-2.5 py-1 text-[9px] uppercase tracking-[0.22em] text-champagne backdrop-blur-md">
              编辑精选
            </span>
          )}
          {discount > 0 && (
            <span className="rounded-full bg-ember/90 px-2.5 py-1 text-[9px] font-semibold tracking-[0.12em] text-white">
              -{discount}%
            </span>
          )}
        </div>

        {similarityPercent !== null && (
          <span className="absolute right-3 top-3 rounded-full border border-sage/40 bg-black/40 px-2.5 py-1 text-[9px] tracking-[0.12em] text-sage backdrop-blur-md">
            相似 {similarityPercent}%
          </span>
        )}
      </div>

      <div className="mt-3.5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={`/product/${product.id}`}
            className="block truncate text-[15px] text-ivory transition hover:text-champagne"
          >
            {product.name}
          </Link>
          <p className="mt-0.5 truncate text-xs text-ivory/55">{product.subtitle}</p>
          {soldOut ? (
            <p className="mt-1 text-[10px] tracking-[0.08em] text-ember/80">暂时售罄</p>
          ) : lowStock ? (
            <p className="mt-1 text-[10px] tracking-[0.08em] text-ember/80">仅剩 {stock} 件</p>
          ) : null}
        </div>
        <span className="flex shrink-0 items-center gap-1 text-[10px] text-ivory/55">
          <Star className="h-3 w-3 fill-champagne/70 text-champagne/80" />
          {product.rating.toFixed(1)}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between">
        <PriceTag price={product.price} originalPrice={product.original_price} size="md" />
        <span className="text-[10px] uppercase tracking-[0.16em] text-ivory/55">{product.category}</span>
      </div>
    </article>
  )
}

export default ProductCard
