import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Store } from 'lucide-react'
import type { AssistantProductCard } from '@/types'
import { ImageWithFallback, PriceTag } from '@/components/ui'
import { cn } from '@/lib/cn'

export interface ProductLinkCardProps {
  item: AssistantProductCard
  className?: string
}

function isInternal(url: string): boolean {
  return url.startsWith('/') && !url.startsWith('//')
}

function LinkShell({
  href,
  internal,
  className,
  children,
}: {
  href: string
  internal: boolean
  className?: string
  children: ReactNode
}) {
  if (internal) {
    return (
      <Link to={href} className={className}>
        {children}
      </Link>
    )
  }
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
    </a>
  )
}

export function ProductLinkCard({ item, className }: ProductLinkCardProps) {
  const product = item.product
  const platformUrl = item.platform_url || `/product/${product.id}`
  const mallUrl = item.mall_url || ''

  return (
    <article
      className={cn(
        'group flex gap-3 rounded-2xl border border-white/10 bg-black/25 p-2.5 transition duration-300 hover:border-champagne/30 hover:bg-black/35',
        className,
      )}
    >
      <LinkShell
        href={platformUrl}
        internal={isInternal(platformUrl)}
        className="block w-[74px] shrink-0 overflow-hidden rounded-xl border border-white/8 focus-visible:outline-offset-[-3px]"
      >
        <ImageWithFallback
          src={product.image}
          alt={product.name}
          loading="eager"
          className="aspect-[3/4] w-full object-cover transition duration-500 group-hover:scale-[1.04]"
        />
      </LinkShell>

      <div className="flex min-w-0 flex-1 flex-col">
        <LinkShell
          href={platformUrl}
          internal={isInternal(platformUrl)}
          className="block truncate text-[12px] text-ivory/85 transition hover:text-champagne"
        >
          {product.name}
        </LinkShell>
        <p className="mt-0.5 truncate text-[9px] text-ivory/55">{product.subtitle || product.category}</p>
        <div className="mt-1">
          <PriceTag price={product.price} originalPrice={product.original_price} size="sm" />
        </div>

        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-2 text-[10px]">
          <LinkShell
            href={platformUrl}
            internal={isInternal(platformUrl)}
            className="inline-flex items-center gap-1 text-ivory/55 transition hover:text-champagne"
          >
            平台商品页 <ArrowUpRight className="h-2.5 w-2.5" />
          </LinkShell>
          {mallUrl ? (
            <a
              href={mallUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-ivory/55 transition hover:text-sage"
            >
              <Store className="h-2.5 w-2.5" /> 云裳商城
            </a>
          ) : (
            <span className="inline-flex items-center gap-1 text-ivory/55">
              <Store className="h-2.5 w-2.5" /> 商城链接待生成
            </span>
          )}
        </div>
      </div>
    </article>
  )
}

export default ProductLinkCard
