import type { ReactNode } from 'react'
import type { Product } from '@/types'
import { cn } from '@/lib/cn'
import ProductCard from './ProductCard'

interface ProductGridProps {
  products: Product[]
  loading?: boolean
  skeletonCount?: number
  className?: string
  empty?: ReactNode
}

const GRID_CLASS = 'grid grid-cols-2 gap-x-4 gap-y-9 md:grid-cols-3 md:gap-x-6 lg:grid-cols-4'

/** 商品卡片的加载骨架，保持与 ProductCard 相近的尺寸，避免布局跳动。 */
export function ProductCardSkeleton() {
  return (
    <div className="animate-pulse motion-reduce:animate-none" aria-hidden="true">
      <div className="aspect-[3/4] rounded-[22px] border border-white/8 bg-white/[0.04]" />
      <div className="mt-4 h-3.5 w-2/3 rounded-full bg-white/[0.06]" />
      <div className="mt-2 h-3 w-1/3 rounded-full bg-white/[0.04]" />
      <div className="mt-3 h-4 w-1/2 rounded-full bg-white/[0.05]" />
    </div>
  )
}

/**
 * 商品网格。加载时渲染骨架屏，空列表时渲染调用方传入的空状态。
 * 仅供商品页使用；ProductCard 的 props 保持稳定，T8 可直接复用。
 */
export function ProductGrid({
  products,
  loading = false,
  skeletonCount = 8,
  className,
  empty = null,
}: ProductGridProps) {
  if (loading) {
    return (
      <div className={cn(GRID_CLASS, className)} aria-busy="true" aria-label="正在加载商品">
        {Array.from({ length: skeletonCount }, (_, index) => (
          <ProductCardSkeleton key={index} />
        ))}
      </div>
    )
  }

  if (products.length === 0) return <>{empty}</>

  return (
    <div className={cn(GRID_CLASS, className)}>
      {products.map((product, index) => (
        <ProductCard key={product.id} product={product} priority={index < 4} />
      ))}
    </div>
  )
}

export default ProductGrid
