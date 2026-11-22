import { create } from 'zustand'

export type ToastType = 'success' | 'error' | 'info'

export interface ToastItem {
  id: string
  type: ToastType
  title: string
  message?: string
  duration: number
}

interface ToastState {
  items: ToastItem[]
  push: (toast: Omit<ToastItem, 'id' | 'duration'> & { duration?: number }) => string
  dismiss: (id: string) => void
  clear: () => void
}

const MAX_TOASTS = 4
const timers = new Map<string, number>()

function makeId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function clearTimer(id: string): void {
  const timer = timers.get(id)
  if (timer !== undefined) {
    window.clearTimeout(timer)
    timers.delete(id)
  }
}

export const useToastStore = create<ToastState>((set, get) => ({
  items: [],

  push: (toast) => {
    const id = makeId()
    const duration = toast.duration ?? (toast.type === 'error' ? 6000 : 4200)
    const item: ToastItem = { ...toast, id, duration }
    set((state) => {
      let items = state.items
      if (items.length >= MAX_TOASTS) {
        const overflow = items.slice(0, items.length - MAX_TOASTS + 1)
        overflow.forEach((old) => clearTimer(old.id))
        items = items.slice(overflow.length)
      }
      return { items: [...items, item] }
    })
    if (duration > 0) {
      timers.set(
        id,
        window.setTimeout(() => get().dismiss(id), duration),
      )
    }
    return id
  },

  dismiss: (id) => {
    clearTimer(id)
    set((state) => ({ items: state.items.filter((item) => item.id !== id) }))
  },

  clear: () => {
    timers.forEach((timer) => window.clearTimeout(timer))
    timers.clear()
    set({ items: [] })
  },
}))

export function useToast() {
  const push = useToastStore((state) => state.push)
  const dismiss = useToastStore((state) => state.dismiss)
  return {
    push,
    dismiss,
    success: (title: string, message?: string) => push({ type: 'success', title, message }),
    error: (title: string, message?: string) =>
      push({ type: 'error', title, message, duration: 6000 }),
    info: (title: string, message?: string) => push({ type: 'info', title, message }),
  }
}
