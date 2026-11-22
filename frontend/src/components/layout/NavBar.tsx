import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { ChevronDown, Menu, ShoppingBag, Sparkles, UserRound, X } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { useCartStore } from '@/store/cart'
import { useToast } from '@/store/toast'
import { useMeta } from '@/lib/useMeta'
import { cn } from '@/lib/cn'

const links = [
  { to: '/shop', label: '本季衣橱' },
  { to: '/graph', label: '知识图谱' },
  { to: '/assistant', label: 'AI 购物助理' },
  { to: '/stylist', label: '五智造型室' },
]

export function NavBar() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const count = useCartStore((state) => state.cart?.total_quantity ?? 0)
  const loadCart = useCartStore((state) => state.load)
  const { meta, loading: metaLoading, error: metaError } = useMeta()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()

  const [menuOpen, setMenuOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const headerRef = useRef<HTMLElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const accountButtonRef = useRef<HTMLButtonElement>(null)
  const accountMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMenuOpen(false)
    setAccountOpen(false)
  }, [location.pathname, location.search])

  useEffect(() => {
    if (user) void loadCart()
  }, [user, loadCart])

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) {
        setMenuOpen(false)
        setAccountOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (accountOpen) {
        setAccountOpen(false)
        accountButtonRef.current?.focus()
      } else if (menuOpen) {
        setMenuOpen(false)
        menuButtonRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen, accountOpen])

  const handleLogout = async () => {
    setMenuOpen(false)
    setAccountOpen(false)
    await logout()
    toast.success('已退出登录', '期待与你的下一次相遇')
    navigate('/')
  }

  const openAccountMenu = () => {
    setAccountOpen(true)
    window.requestAnimationFrame(() => {
      const first = accountMenuRef.current?.querySelector<HTMLElement>('a, button')
      first?.focus()
    })
  }

  const mode = meta?.mode
  const modeText = mode === 'qwen' ? 'QWEN' : mode === 'mock' ? 'MOCK' : metaLoading ? '连接中' : '离线'
  const modeTitle =
    mode === 'qwen'
      ? '通义千问已连接'
      : mode === 'mock'
        ? '当前为本地 Mock 演示模式，无需 API Key'
        : (metaError ?? '正在读取运行模式')

  return (
    <header ref={headerRef} className="fixed inset-x-0 top-0 z-[90] page-pad py-3 md:py-4">
      <nav
        aria-label="主导航"
        className="glass mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-3 rounded-full px-3.5 md:h-16 md:px-5"
      >
        <Link
          to="/"
          className="flex shrink-0 items-baseline gap-2 rounded-full py-2 pl-1 pr-2"
          aria-label="衣见 ATELIER 首页"
        >
          <span className="display text-[22px] tracking-[0.16em] text-ivory md:text-[24px]">衣见</span>
          <span className="hidden text-[9px] uppercase tracking-[0.42em] text-champagne/90 sm:block">
            ATELIER
          </span>
        </Link>

        <div className="hidden items-center gap-0.5 lg:flex">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                cn(
                  'rounded-full px-3.5 py-2 text-[12px] tracking-[0.1em] text-ivory/60 transition hover:bg-white/[0.05] hover:text-ivory xl:px-4',
                  isActive && 'bg-white/[0.08] text-ivory',
                )
              }
            >
              {link.label}
            </NavLink>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <span
            className={cn(
              'hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] tracking-[0.16em] sm:flex',
              mode === 'qwen'
                ? 'border-sage/40 bg-sage/10 text-sage'
                : mode === 'mock'
                  ? 'border-champagne/25 bg-champagne/5 text-champagne/90'
                  : metaError
                    ? 'border-ember/30 bg-ember/5 text-ember/80'
                    : 'border-white/10 bg-white/[0.03] text-ivory/55',
            )}
            title={modeTitle}
            aria-label={modeTitle}
          >
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            {modeText}
          </span>

          <Link
            to="/cart"
            className="relative rounded-full p-2.5 text-ivory/65 transition hover:bg-white/[0.08] hover:text-ivory"
            aria-label={`购物袋，当前 ${count} 件商品`}
          >
            <ShoppingBag className="h-[18px] w-[18px]" aria-hidden="true" />
            {count > 0 ? (
              <span
                className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-ember px-1 text-[9px] font-semibold text-white"
                aria-hidden="true"
              >
                {count > 99 ? '99+' : count}
              </span>
            ) : null}
            <span className="sr-only" aria-live="polite">
              {count > 0 ? `购物袋中有 ${count} 件商品` : '购物袋为空'}
            </span>
          </Link>

          {user ? (
            <div
              className="relative hidden lg:block"
              onBlur={(event) => {
                const next = event.relatedTarget as Node | null
                if (next && !event.currentTarget.contains(next)) setAccountOpen(false)
              }}
            >
              <button
                ref={accountButtonRef}
                type="button"
                className="flex items-center gap-2 rounded-full px-2.5 py-2 text-[12px] text-ivory/65 transition hover:bg-white/[0.08] hover:text-ivory"
                aria-haspopup="true"
                aria-expanded={accountOpen}
                aria-controls="account-menu"
                onClick={() => setAccountOpen((value) => !value)}
                onKeyDown={(event) => {
                  if (!accountOpen && event.key === 'ArrowDown') {
                    event.preventDefault()
                    openAccountMenu()
                  }
                }}
              >
                <UserRound className="h-4 w-4" aria-hidden="true" />
                <span className="max-w-[6rem] truncate">{user.nickname || user.username}</span>
                <ChevronDown
                  className={cn('h-3 w-3 transition-transform', accountOpen && 'rotate-180')}
                  aria-hidden="true"
                />
              </button>
              <div
                ref={accountMenuRef}
                id="account-menu"
                className={cn(
                  'absolute right-0 top-full mt-2 w-44 rounded-2xl border border-white/10 bg-ink-900/95 p-1.5 shadow-2xl backdrop-blur-xl transition duration-200',
                  accountOpen
                    ? 'visible translate-y-0 opacity-100'
                    : 'invisible translate-y-1 opacity-0',
                )}
              >
                <p className="truncate px-3 py-2 text-[10px] uppercase tracking-[0.18em] text-ivory/55">
                  {user.nickname || user.username}
                </p>
                <Link
                  to="/orders"
                  className="block rounded-xl px-3 py-2 text-xs text-ivory/70 transition hover:bg-white/[0.06] hover:text-ivory"
                  onClick={() => setAccountOpen(false)}
                >
                  我的订单
                </Link>
                <button
                  type="button"
                  onClick={() => void handleLogout()}
                  className="block w-full rounded-xl px-3 py-2 text-left text-xs text-ivory/70 transition hover:bg-white/[0.06] hover:text-ivory"
                >
                  退出登录
                </button>
              </div>
            </div>
          ) : (
            <Link
              to="/auth"
              className="hidden rounded-full border border-champagne/25 bg-champagne/[0.08] px-4 py-2 text-[11px] tracking-[0.14em] text-champagne transition hover:bg-champagne/[0.14] lg:block"
            >
              登录 / 注册
            </Link>
          )}

          <button
            ref={menuButtonRef}
            type="button"
            className="rounded-full p-2.5 text-ivory/70 transition hover:bg-white/[0.08] lg:hidden"
            onClick={() => setMenuOpen((value) => !value)}
            aria-label={menuOpen ? '关闭菜单' : '打开菜单'}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
          >
            {menuOpen ? (
              <X className="h-5 w-5" aria-hidden="true" />
            ) : (
              <Menu className="h-5 w-5" aria-hidden="true" />
            )}
          </button>
        </div>
      </nav>

      {menuOpen ? (
        <div
          id="mobile-nav"
          className="glass-strong mx-auto mt-2 max-h-[calc(100dvh-6.5rem)] max-w-[1440px] overflow-y-auto overscroll-contain rounded-3xl p-2.5 lg:hidden"
        >
          <nav aria-label="移动端导航">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  cn(
                    'block rounded-2xl px-4 py-3 text-sm text-ivory/75 transition hover:bg-white/[0.06] hover:text-ivory',
                    isActive && 'bg-white/[0.08] text-ivory',
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="my-1.5 h-px bg-white/[0.08]" />
          {user ? (
            <>
              <p className="truncate px-4 py-1.5 text-[10px] uppercase tracking-[0.2em] text-ivory/55">
                {user.nickname || user.username}
              </p>
              <Link
                to="/orders"
                className="block rounded-2xl px-4 py-3 text-sm text-ivory/75 transition hover:bg-white/[0.06]"
              >
                我的订单
              </Link>
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="block w-full rounded-2xl px-4 py-3 text-left text-sm text-ivory/55 transition hover:bg-white/[0.04] hover:text-ivory/80"
              >
                退出登录
              </button>
            </>
          ) : (
            <Link to="/auth" className="block rounded-2xl px-4 py-3 text-sm text-champagne">
              登录 / 注册
            </Link>
          )}
        </div>
      ) : null}
    </header>
  )
}

export default NavBar
