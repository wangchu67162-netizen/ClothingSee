import { useEffect, useState, type ImgHTMLAttributes } from 'react'

interface ImageWithFallbackProps extends ImgHTMLAttributes<HTMLImageElement> {
  fallback?: string
}

export function ImageWithFallback({
  fallback = '/images/fallback/garment.svg',
  onError,
  onLoad,
  src,
  alt = '',
  ...rest
}: ImageWithFallbackProps) {
  const initial = typeof src === 'string' && src ? src : fallback
  const [current, setCurrent] = useState(initial)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setCurrent(typeof src === 'string' && src ? src : fallback)
    setFailed(false)
  }, [src, fallback])

  const usingFallback = current === fallback

  return (
    <img
      {...rest}
      src={current}
      alt={alt}
      loading={rest.loading ?? 'lazy'}
      decoding={rest.decoding ?? 'async'}
      data-fallback={usingFallback ? 'true' : undefined}
      data-failed={failed ? 'true' : undefined}
      onLoad={(event) => {
        setFailed(false)
        onLoad?.(event)
      }}
      onError={(event) => {
        if (!usingFallback) {
          setCurrent(fallback)
        } else {
          setFailed(true)
        }
        onError?.(event)
      }}
    />
  )
}

export default ImageWithFallback
