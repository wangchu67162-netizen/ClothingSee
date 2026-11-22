import { useEffect, useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from 'react'
import { Camera, ImagePlus, Loader2, UploadCloud, X } from 'lucide-react'
import { GlassButton } from '@/components/ui'
import { cn } from '@/lib/cn'

export interface UploadDropProps {
  onFile: (file: File) => void
  loading?: boolean
  onClear?: () => void
  className?: string
}

const SAMPLE_URL = '/static/images/samples/outfit-demo.webp'
const MAX_SIZE = 8 * 1024 * 1024

export function UploadDrop({ onFile, loading = false, onClear, className }: UploadDropProps) {
  const [preview, setPreview] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [sampleLoading, setSampleLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<string | null>(null)

  useEffect(() => {
    previewRef.current = preview
  }, [preview])

  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [],
  )

  const accept = (file: File | null | undefined) => {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('请选择 JPG、PNG 或 WebP 图片')
      return
    }
    if (file.size > MAX_SIZE) {
      setError('图片不能超过 8MB，请压缩后再试')
      return
    }
    setError('')
    setFileName(file.name)
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    const url = URL.createObjectURL(file)
    previewRef.current = url
    setPreview(url)
    onFile(file)
  }

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    accept(event.target.files?.[0])
    event.target.value = ''
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    if (loading) return
    accept(event.dataTransfer.files?.[0])
  }

  const clear = () => {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = null
    setPreview(null)
    setFileName('')
    setError('')
    onClear?.()
  }

  const loadSample = async () => {
    if (loading || sampleLoading) return
    setSampleLoading(true)
    setError('')
    try {
      const response = await fetch(SAMPLE_URL, { cache: 'no-cache' })
      if (!response.ok) throw new Error(String(response.status))
      const blob = await response.blob()
      const file = new File([blob], '衣见样例穿搭.webp', { type: blob.type || 'image/webp' })
      accept(file)
    } catch {
      setError('样例图加载失败，请改用本地图片')
    } finally {
      setSampleLoading(false)
    }
  }

  const openPicker = () => {
    if (!loading) inputRef.current?.click()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openPicker()
    }
  }

  return (
    <div className={cn('flex flex-col', className)}>
      <div
        role="button"
        tabIndex={0}
        aria-label="上传穿搭照片"
        onClick={openPicker}
        onKeyDown={onKeyDown}
        onDragOver={(event) => {
          event.preventDefault()
          if (!loading) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'group relative flex min-h-[232px] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-[22px] border border-dashed transition duration-300',
          dragging ? 'border-champagne/70 bg-champagne/8' : 'border-white/15 bg-black/20 hover:border-champagne/40',
          loading && 'cursor-wait',
        )}
      >
        {preview ? (
          <>
            <img src={preview} alt="已选择图片预览" className="absolute inset-0 h-full w-full object-cover" />
            <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-black/20" />
            <div className="relative mt-auto flex w-full items-end justify-between gap-3 p-4">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-[0.2em] text-champagne/85">已选择</p>
                <p className="mt-1 truncate text-xs text-ivory/80">{fileName}</p>
              </div>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  clear()
                }}
                className="rounded-full bg-black/50 p-2 text-ivory/70 backdrop-blur transition hover:text-ember"
                aria-label="移除图片"
                disabled={loading}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </>
        ) : (
          <>
            <span className="flex h-14 w-14 items-center justify-center rounded-full border border-white/12 bg-white/[0.03] text-champagne/70 transition group-hover:border-champagne/35 group-hover:text-champagne">
              <UploadCloud className="h-6 w-6" />
            </span>
            <p className="mt-4 text-sm text-ivory/70">拖入或点击上传一张穿搭照</p>
            <p className="mt-1 text-[10px] text-ivory/55">JPG / PNG / WebP · 最大 8MB · 仅用于本次演示</p>
          </>
        )}

        {loading && (
          <div className="absolute inset-0 z-[1] flex flex-col items-center justify-center gap-2 bg-black/55 backdrop-blur-sm">
            <Loader2 className="h-6 w-6 animate-spin text-champagne" />
            <p className="text-[11px] text-ivory/70">正在处理图片…</p>
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={onInputChange}
          disabled={loading}
        />
      </div>

      {error && (
        <p className="mt-2 rounded-xl border border-ember/25 bg-ember/5 px-3 py-2 text-[10px] text-ember">{error}</p>
      )}

      <div className="mt-3 flex gap-2">
        <GlassButton
          type="button"
          size="sm"
          className="flex-1"
          icon={<ImagePlus className="h-3.5 w-3.5" />}
          onClick={openPicker}
          disabled={loading}
        >
          选择照片
        </GlassButton>
        <GlassButton
          type="button"
          size="sm"
          variant="ghost"
          className="flex-1"
          icon={sampleLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Camera className="h-3.5 w-3.5" />}
          onClick={() => void loadSample()}
          disabled={loading || sampleLoading}
        >
          使用样例图
        </GlassButton>
      </div>
    </div>
  )
}

export default UploadDrop
