import { useEffect, useRef, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import { AppErrorBoundary, FullPageLoader } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import Landing from '@/pages/Landing'
import Auth from '@/pages/Auth'
import Shop from '@/pages/Shop'
import ProductDetail from '@/pages/ProductDetail'
import Cart from '@/pages/Cart'
import Checkout from '@/pages/Checkout'
import Orders from '@/pages/Orders'
import Assistant from '@/pages/Assistant'
import Stylist from '@/pages/Stylist'
import KnowledgeGraph from '@/pages/KnowledgeGraph'
import NotFound from '@/pages/NotFound'

const ROUTE_TITLES: Record<string, string> = {
  '/': '首页',
  '/shop': '本季衣橱',
  '/auth': '登录 / 注册',
  '/cart': '购物袋',
  '/checkout': '结算',
  '/orders': '我的订单',
  '/assistant': 'AI 购物助理',
  '/stylist': '五智造型室',
  '/graph': '服装知识图谱',
}

function ScrollToTop() {
  const { pathname, hash } = useLocation()
  const previousPath = useRef(pathname)
  useEffect(() => {
    if (previousPath.current !== pathname) {
      previousPath.current = pathname
      window.scrollTo({ top: 0, behavior: 'auto' })
      return
    }
    if (!hash) return
    // 同一页面内 hash 跳转：分屏页由 PageDeck 处理容器滚动，其余页面滚动到锚点
    const target = document.getElementById(decodeURIComponent(hash.slice(1)))
    if (target && !target.closest('.deck-scroll')) {
      target.scrollIntoView({ block: 'start', behavior: 'auto' })
    }
  }, [pathname, hash])
  return null
}

function RouteMeta() {
  const { pathname } = useLocation()
  useEffect(() => {
    const base = '衣见 ATELIER · AI 服装买手店'
    const label = pathname.startsWith('/product/')
      ? '商品详情'
      : (ROUTE_TITLES[pathname] ?? '未找到页面')
    document.title = pathname === '/' ? base : `${label} · 衣见 ATELIER`
    const description = document.querySelector('meta[name="description"]')
    if (description) {
      description.setAttribute(
        'content',
        pathname === '/'
          ? '衣见 ATELIER — 视觉小模型与五位 AI 智能体共议的 AI 高级服装买手店'
          : `${label} — 衣见 ATELIER，AI 服装买手店课程演示项目`,
      )
    }
  }, [pathname])
  return null
}

function Protected({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const location = useLocation()
  if (!hydrated) return <FullPageLoader label="正在确认你的身份" />
  if (!user) {
    const next = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to={`/auth?next=${encodeURIComponent(next)}`} replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <RouteMeta />
      <AppErrorBoundary>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Landing />} />
            <Route path="shop" element={<Shop />} />
            <Route path="product/:id" element={<ProductDetail />} />
            <Route path="graph" element={<KnowledgeGraph />} />
            <Route path="auth" element={<Auth />} />
            <Route
              path="cart"
              element={
                <Protected>
                  <Cart />
                </Protected>
              }
            />
            <Route
              path="checkout"
              element={
                <Protected>
                  <Checkout />
                </Protected>
              }
            />
            <Route
              path="orders"
              element={
                <Protected>
                  <Orders />
                </Protected>
              }
            />
            <Route
              path="assistant"
              element={
                <Protected>
                  <Assistant />
                </Protected>
              }
            />
            <Route
              path="stylist"
              element={
                <Protected>
                  <Stylist />
                </Protected>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AppErrorBoundary>
    </>
  )
}
