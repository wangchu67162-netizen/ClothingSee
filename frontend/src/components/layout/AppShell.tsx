import { useEffect } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Starfield, FlameTrail, CursorGlow, NoiseOverlay } from '@/components/effects'
import { AppErrorBoundary, ToastHost } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import { useCartStore } from '@/store/cart'
import { useToastStore } from '@/store/toast'
import NavBar from './NavBar'
import Footer from './Footer'

const PROTECTED_PREFIXES = ['/cart', '/checkout', '/orders', '/assistant', '/stylist']

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  )
}

export function AppShell() {
  const hydrate = useAuthStore((state) => state.hydrate)
  const user = useAuthStore((state) => state.user)
  const loadCart = useCartStore((state) => state.load)
  const resetCart = useCartStore((state) => state.reset)
  const location = useLocation()
  const navigate = useNavigate()
  const isDeck = location.pathname === '/' || location.pathname === '/stylist'

  useEffect(() => {
    void hydrate()
  }, [hydrate])

  useEffect(() => {
    if (user) void loadCart()
    else resetCart()
  }, [user, loadCart, resetCart])

  useEffect(() => {
    const onUnauthorized = () => {
      if (location.pathname === '/auth') return
      useToastStore.getState().push({
        type: 'error',
        title: '登录状态已失效',
        message: '请重新登录后继续操作',
      })
      if (isProtectedPath(location.pathname)) {
        const next = `${location.pathname}${location.search}`
        navigate(`/auth?next=${encodeURIComponent(next)}`, { replace: true })
      }
    }
    window.addEventListener('yijian:unauthorized', onUnauthorized)
    return () => window.removeEventListener('yijian:unauthorized', onUnauthorized)
  }, [location.pathname, location.search, navigate])

  return (
    <div className="relative min-h-[100dvh] overflow-x-clip">
      <a href="#main" className="skip-link">
        跳到主要内容
      </a>

      <div className="aurora" aria-hidden="true" />
      <Starfield />
      <CursorGlow />
      <NoiseOverlay />
      <FlameTrail />

      <NavBar />

      <main
        id="main"
        tabIndex={-1}
        className={isDeck ? 'relative z-10' : 'relative z-10 pb-16 pt-24 md:pt-28'}
      >
        <AppErrorBoundary key={location.pathname}>
          <Outlet />
        </AppErrorBoundary>
      </main>

      {!isDeck ? <Footer /> : null}
      <ToastHost />
    </div>
  )
}

export default AppShell
