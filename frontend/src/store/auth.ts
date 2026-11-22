import { create } from 'zustand'
import {
  ApiError,
  api,
  apiErrorMessage,
  clearSession,
  getToken,
  readStoredUser,
  writeSession,
  writeStoredUser,
} from '@/lib/api'
import type { AuthResponse, User } from '@/types'

interface AuthState {
  user: User | null
  token: string | null
  loading: boolean
  hydrated: boolean
  error: string | null
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, nickname?: string) => Promise<void>
  logout: () => Promise<void>
  /** 401 / 主动失效时清空本地登录态（不发请求） */
  expire: () => void
  hydrate: () => Promise<void>
  isAuthenticated: () => boolean
}

let hydratePromise: Promise<void> | null = null

export const useAuthStore = create<AuthState>((set, get) => ({
  user: readStoredUser(),
  token: getToken(),
  loading: false,
  hydrated: false,
  error: null,

  login: async (username, password) => {
    set({ loading: true, error: null })
    try {
      const data = await api.post<AuthResponse>(
        '/auth/login',
        { username, password },
        { auth: false },
      )
      writeSession(data.access_token, data.user)
      set({ user: data.user, token: data.access_token, loading: false, hydrated: true, error: null })
    } catch (error) {
      const message = apiErrorMessage(error)
      set({ loading: false, error: message })
      throw error
    }
  },

  register: async (username, password, nickname = '') => {
    set({ loading: true, error: null })
    try {
      const data = await api.post<AuthResponse>(
        '/auth/register',
        { username, password, nickname },
        { auth: false },
      )
      writeSession(data.access_token, data.user)
      set({ user: data.user, token: data.access_token, loading: false, hydrated: true, error: null })
    } catch (error) {
      const message = apiErrorMessage(error)
      set({ loading: false, error: message })
      throw error
    }
  },

  logout: async () => {
    try {
      const token = getToken()
      if (token) {
        // 手动带 token 且 auth:false：退出时的 401 不再触发全局“登录失效”提示
        await api.post('/auth/logout', undefined, {
          auth: false,
          headers: { Authorization: `Bearer ${token}` },
          timeout: 8_000,
        })
      }
    } catch {
      /* 服务端不可达也允许本地退出 */
    } finally {
      clearSession()
      set({ user: null, token: null, hydrated: true, loading: false, error: null })
    }
  },

  expire: () => {
    clearSession()
    set({ user: null, token: null, hydrated: true, loading: false })
  },

  hydrate: async () => {
    if (get().hydrated) return
    if (hydratePromise) return hydratePromise
    const token = getToken()
    if (!token) {
      set({ user: null, token: null, hydrated: true, loading: false })
      return
    }
    hydratePromise = (async () => {
      try {
        const user = await api.get<User>('/auth/me', { timeout: 12_000 })
        writeStoredUser(user)
        set({ user, token, hydrated: true, loading: false, error: null })
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          clearSession()
          set({ user: null, token: null, hydrated: true, loading: false, error: null })
        } else {
          // 网络故障时保留本地缓存用户，避免把用户误踢下线
          const cachedUser = readStoredUser()
          set({
            user: cachedUser,
            token,
            hydrated: true,
            loading: false,
            error: apiErrorMessage(error),
          })
        }
      } finally {
        hydratePromise = null
      }
    })()
    return hydratePromise
  },

  isAuthenticated: () => Boolean(get().user && getToken()),
}))

/* 任意请求收到 401 时同步清空 store，即使当前不在 AppShell 监听范围 */
if (typeof window !== 'undefined') {
  window.addEventListener('yijian:unauthorized', () => {
    const state = useAuthStore.getState()
    if (state.user || state.token) state.expire()
  })
}
