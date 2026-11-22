import { cn } from '@/lib/cn'
import { formatPrice } from '@/lib/format'

interface PriceTagProps {
  price: number
  originalPrice?: number | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function PriceTag({ price, originalPrice, size = 'md', className }: PriceTagProps) {
  const priceClass =
    size === 'lg' ? 'text-2xl md:text-3xl' : size === 'sm' ? 'text-sm' : 'text-lg'
  const discounted = Boolean(originalPrice && originalPrice > price)
  const label = discounted
    ? `现价 ${formatPrice(price)}，原价 ${formatPrice(originalPrice)}`
    : `价格 ${formatPrice(price)}`
  return (
    <span
      className={cn('inline-flex items-baseline gap-2 font-display', className)}
      aria-label={label}
    >
      <span className={cn(priceClass, 'text-champagne')}>{formatPrice(price)}</span>
      {discounted ? (
        <span className="text-xs text-ivory/55 line-through" aria-hidden="true">
          {formatPrice(originalPrice)}
        </span>
      ) : null}
    </span>
  )
}

export default PriceTag
