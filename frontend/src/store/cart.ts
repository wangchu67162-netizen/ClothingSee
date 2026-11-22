import { create } from 'zustand'
import { api, apiErrorMessage } from '@/lib/api'
import type { Cart } from '@/types'

interface CartState {
  cart: Cart | null
  loading: boolean
  error: string | null
  load: () => Promise<void>
  add: (productId: number, options?: { quantity?: number; size?: string; color?: string }) => Promise<void>
  update: (itemId: number, quantity: number) => Promise<void>
  remove: (itemId: number) => Promise<void>
  clear: () => Promise<void>
  reset: () => void
  count: () => number
}

/* 用递增序号丢弃过期响应，避免 load 与 add/update 并发时相互覆盖 */
let requestSeq = 0
let loadPromise: Promise<void> | null = null

export const useCartStore = create<CartState>((set, get) => ({
  cart: null,
  loading: false,
  error: null,

  load: async () => {
    if (loadPromise) return loadPromise
    const current = ++requestSeq
    set({ loading: true, error: null })
    loadPromise = (async () => {
      try {
        const cart = await api.get<Cart>('/cart')
        if (current === requestSeq) set({ cart, loading: false })
      } catch (error) {
        if (current === requestSeq) set({ loading: false, error: apiErrorMessage(error) })
      } finally {
        loadPromise = null
      }
    })()
    return loadPromise
  },

  add: async (productId, options = {}) => {
    const current = ++requestSeq
    set({ loading: true, error: null })
    try {
      const cart = await api.post<Cart>('/cart', {
        product_id: productId,
        quantity: options.quantity ?? 1,
        size: options.size ?? '',
        color: options.color ?? '',
      })
      if (current === requestSeq) set({ cart, loading: false })
    } catch (error) {
      if (current === requestSeq) set({ loading: false, error: apiErrorMessage(error) })
      throw error
    }
  },

  update: async (itemId, quantity) => {
    const current = ++requestSeq
    set({ loading: true, error: null })
    try {
      const cart = await api.patch<Cart>(`/cart/${itemId}`, { quantity })
      if (current === requestSeq) set({ cart, loading: false })
    } catch (error) {
      if (current === requestSeq) set({ loading: false, error: apiErrorMessage(error) })
      throw error
    }
  },

  remove: async (itemId) => {
    const current = ++requestSeq
    set({ loading: true, error: null })
    try {
      const cart = await api.del<Cart>(`/cart/${itemId}`)
      if (current === requestSeq) set({ cart, loading: false })
    } catch (error) {
      if (current === requestSeq) set({ loading: false, error: apiErrorMessage(error) })
      throw error
    }
  },

  clear: async () => {
    const current = ++requestSeq
    set({ loading: true, error: null })
    try {
      const cart = await api.del<Cart>('/cart')
      if (current === requestSeq) set({ cart, loading: false })
    } catch (error) {
      if (current === requestSeq) set({ loading: false, error: apiErrorMessage(error) })
      throw error
    }
  },

  reset: () => {
    requestSeq += 1
    loadPromise = null
    set({ cart: null, loading: false, error: null })
  },

  count: () => get().cart?.total_quantity ?? 0,
}))
