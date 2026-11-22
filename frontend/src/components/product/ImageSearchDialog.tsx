import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { ImagePlus, Loader2, Search, Sparkles, UploadCloud } from 'lucide-react'
import type { ImageSearchResult } from '@/types'
import { ApiError, api } from '@/lib/api'
import { GlassButton, Modal } from '@/components/ui'
import { cn } from '@/lib/cn'

const SAMPLE_URL = '/static/images/samples/outfit-demo.webp'
const MAX_BYTES = 10 * 1024 * 1024

interface ImageSearchDialogProps {
  open: boolean
  onClose: () => void
  onResults: (result: ImageSearchResult) => void
}

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return `图片搜索暂不可用${error.detail ? `（${error.detail}）` : ''}。你仍可以使用文字搜索，或稍后再试。`
    }
    if (error.status === 413) return '图片体积过大，请选择 10MB 以内的图片。'
    if (error.status === 415) return '暂不支持该图片格式，请选择 JPG、PNG 或 WebP。'
    return error.detail || '图片搜索失败，请稍后重试。'
  }
  return '网络异常，图片搜索没有完成，请稍后重试，或改用文字搜索。'
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/**
 * 图片搜索入口。成功后把结果交给 Shop 展示；503（视觉小模型未启用）给出中文友好提示。
 */
export function ImageSearchDialog({ open, onClose, onResults }: ImageSearchDialogProps) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingSample, setLoadingSample] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (open) return
    abortRef.current?.abort()
    abortRef.current = null
    setFile(null)
    setDragOver(false)
    setLoading(false)
    setLoadingSample(false)
    setError(null)
  }, [open])

  useEffect(() => {
    if (!file) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => () => abortRef.current?.abort(), [])

  const acceptFile = (candidate: File | null | undefined) => {
    if (!candidate) return
    if (!candidate.type.startsWith('image/')) {
      setError('请选择图片文件（JPG、PNG 或 WebP）。')
      return
    }
    if (candidate.size > MAX_BYTES) {
      setError('图片体积过大，请选择 10MB 以内的图片。')
      return
    }
    setError(null)
    setFile(candidate)
  }

  const onInput = (event: ChangeEvent<HTMLInputElement>) => {
    acceptFile(event.target.files?.[0])
    event.target.value = ''
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragOver(false)
    acceptFile(event.dataTransfer.files?.[0])
  }

  const loadSample = async () => {
    if (loadingSample) return
    setLoadingSample(true)
    setError(null)
    try {
      const response = await fetch(SAMPLE_URL)
      if (!response.ok) throw new Error('sample unavailable')
      const blob = await response.blob()
      acceptFile(new File([blob], 'outfit-demo.webp', { type: blob.type || 'image/webp' }))
    } catch {
      setError('样例图加载失败，请选择一张本地图片。')
    } finally {
      setLoadingSample(false)
    }
  }

  const submit = async () => {
    if (!file || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('top_k', '8')
      const result = await api.upload<ImageSearchResult>('/products/search-by-image', form, {
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      onResults(result)
      onClose()
    } catch (reason) {
      if (controller.signal.aborted) return
      setError(friendlyError(reason))
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="以图搜衣" className="max-w-2xl">
      <p className="text-xs leading-6 text-ivory/55">
        上传一张穿搭或单品照片，视觉小模型会从本地商品库中找出轮廓、颜色与材质相近的作品。图片仅用于本次相似度检索。
      </p>

      <div
        className={cn(
          'mt-5 rounded-3xl border border-dashed p-5 transition',
          dragOver ? 'border-champagne/70 bg-champagne/8' : 'border-white/15 bg-white/[0.025]',
        )}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        {preview ? (
          <div className="flex items-center gap-4">
            <img
              src={preview}
              alt="待搜索图片预览"
              className="h-24 w-20 rounded-2xl border border-white/10 object-cover"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-ivory/80">{file?.name}</p>
              <p className="mt-1 text-[10px] tracking-[0.12em] text-ivory/55">
                {file ? formatSize(file.size) : ''}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-full border border-white/15 px-3 py-1.5 text-[11px] text-ivory/60 transition hover:border-champagne/40 hover:text-champagne"
                  onClick={() => inputRef.current?.click()}
                >
                  换一张
                </button>
                <button
                  type="button"
                  className="rounded-full px-3 py-1.5 text-[11px] text-ivory/55 transition hover:text-ember"
                  onClick={() => setFile(null)}
                >
                  移除
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="py-4 text-center">
            <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full border border-champagne/25 bg-champagne/8 text-champagne">
              <ImagePlus className="h-6 w-6" />
            </span>
            <p className="mt-4 text-sm text-ivory/70">拖拽图片到这里，或选择本地文件</p>
            <p className="mt-1 text-[10px] tracking-[0.12em] text-ivory/55">
              支持 JPG / PNG / WebP，10MB 以内
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <button
                type="button"
                className="btn-glass h-9 px-4 text-[12px]"
                onClick={() => inputRef.current?.click()}
              >
                <UploadCloud className="h-4 w-4" /> 选择图片
              </button>
              <button
                type="button"
                className="btn-glass h-9 px-4 text-[12px]"
                onClick={loadSample}
                disabled={loadingSample}
              >
                {loadingSample ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                使用样例图
              </button>
            </div>
          </div>
        )}
        <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={onInput} />
      </div>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-2xl border border-ember/20 bg-ember/5 px-4 py-3 text-xs leading-6 text-ember"
        >
          {error}
        </p>
      )}

      <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <GlassButton type="button" variant="ghost" size="md" onClick={onClose}>
          取消
        </GlassButton>
        <GlassButton
          type="button"
          variant="primary"
          size="md"
          loading={loading}
          disabled={!file || loading}
          icon={<Search className="h-4 w-4" />}
          onClick={submit}
        >
          {loading ? '正在检索…' : '开始以图搜衣'}
        </GlassButton>
      </div>
    </Modal>
  )
}

export default ImageSearchDialog
