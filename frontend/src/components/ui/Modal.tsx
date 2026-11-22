import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  className?: string
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function Modal({ open, onClose, title, children, className }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const body = document.body
    const previousOverflow = body.style.overflow
    const previousPadding = body.style.paddingRight
    const scrollbar = window.innerWidth - document.documentElement.clientWidth
    body.style.overflow = 'hidden'
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`

    const panel = panelRef.current
    const getFocusable = () => {
      if (!panel) return [] as HTMLElement[]
      return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.getClientRects().length > 0,
      )
    }

    const focusInitial = window.requestAnimationFrame(() => {
      const nodes = getFocusable()
      if (nodes.length) nodes[0].focus()
      else panel?.focus()
    })

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const nodes = getFocusable()
      if (!nodes.length) {
        event.preventDefault()
        panel?.focus()
        return
      }
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.cancelAnimationFrame(focusInitial)
      document.removeEventListener('keydown', onKeyDown, true)
      body.style.overflow = previousOverflow
      body.style.paddingRight = previousPadding
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title ? undefined : '弹窗'}
      aria-labelledby={title ? titleId : undefined}
    >
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-black/70 backdrop-blur-sm"
        onClick={() => onCloseRef.current()}
        aria-label="关闭弹窗"
        tabIndex={-1}
      />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn(
          'glass-strong relative max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto overscroll-contain rounded-[28px] p-6 outline-none md:p-8',
          className,
        )}
      >
        <div className="mb-4 flex items-center justify-between gap-4">
          {title ? (
            <h2 id={titleId} className="display text-2xl text-ivory">
              {title}
            </h2>
          ) : (
            <span />
          )}
          <button
            type="button"
            className="rounded-full p-2 text-ivory/60 transition hover:bg-white/10 hover:text-ivory"
            onClick={() => onCloseRef.current()}
            aria-label="关闭"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

export default Modal
