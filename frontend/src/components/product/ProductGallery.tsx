import { useState, type KeyboardEvent, type ReactNode } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { ImageWithFallback } from '@/components/ui'
import { cn } from '@/lib/cn'

interface ProductGalleryProps {
  images: string[]
  name: string
  badge?: ReactNode
  className?: string
}

/**
 * 商品图片画廊：缩略图选择 + 左右方向键切换，焦点在主图区域时生效。
 * 父组件可用 key={product.id} 让切换商品时回到第一张。
 */
export function ProductGallery({ images, name, badge, className }: ProductGalleryProps) {
  const [index, setIndex] = useState(0)
  const count = images.length
  if (count === 0) return null

  const current = Math.min(index, count - 1)
  const go = (delta: number) => setIndex((value) => (value + delta + count) % count)

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (count < 2) return
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      go(-1)
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      go(1)
    }
  }

  return (
    <div className={className}>
      <div
        className="group relative overflow-hidden rounded-[30px] border border-white/12 bg-ink-800"
        tabIndex={0}
        role="group"
        aria-roledescription="商品图片轮播"
        aria-label={`${name}，共 ${count} 张图片，使用左右方向键切换`}
        onKeyDown={onKeyDown}
      >
        <ImageWithFallback
          key={images[current]}
          src={images[current]}
          alt={`${name} 图片 ${current + 1} / ${count}`}
          className="aspect-[3/4] w-full object-cover"
          loading="eager"
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950/30 via-transparent to-transparent" />
        {badge && <div className="absolute left-4 top-4">{badge}</div>}

        {count > 1 && (
          <>
            <button
              type="button"
              onClick={() => go(-1)}
              className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full border border-white/15 bg-black/30 p-2.5 text-ivory/70 backdrop-blur-md transition hover:border-champagne/50 hover:text-champagne"
              aria-label="上一张图片"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => go(1)}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full border border-white/15 bg-black/30 p-2.5 text-ivory/70 backdrop-blur-md transition hover:border-champagne/50 hover:text-champagne"
              aria-label="下一张图片"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            <span
              className="absolute bottom-4 right-4 rounded-full border border-white/15 bg-black/40 px-2.5 py-1 text-[10px] tracking-[0.18em] text-ivory/70 backdrop-blur-md"
              aria-live="polite"
            >
              {current + 1} / {count}
            </span>
          </>
        )}
      </div>

      {count > 1 && (
        <div className="mt-3 grid grid-cols-4 gap-2.5" role="group" aria-label="选择商品图片">
          {images.map((image, thumbIndex) => (
            <button
              key={`${image}-${thumbIndex}`}
              type="button"
              onClick={() => setIndex(thumbIndex)}
              aria-label={`查看第 ${thumbIndex + 1} 张图片`}
              aria-pressed={thumbIndex === current}
              className={cn(
                'overflow-hidden rounded-2xl border transition',
                thumbIndex === current
                  ? 'border-champagne/70'
                  : 'border-white/10 opacity-55 hover:opacity-90',
              )}
            >
              <ImageWithFallback src={image} alt="" className="aspect-square w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default ProductGallery
