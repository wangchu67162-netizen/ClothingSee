import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, KeyRound, Sparkles, UserRound } from 'lucide-react'
import { GlassButton, GlassInput, GlassPanel, ImageWithFallback } from '@/components/ui'
import { useAuthStore } from '@/store/auth'
import { apiErrorMessage } from '@/lib/api'
import { cn } from '@/lib/cn'

type Mode = 'login' | 'register'

/** 只允许站内路径，避免 ?next= 造成开放重定向或回到登录页自身。 */
function safeNext(raw: string | null): string {
  if (!raw) return '/'
  if (!raw.startsWith('/') || raw.startsWith('//')) return '/'
  if (raw === '/auth' || raw.startsWith('/auth?') || raw.startsWith('/auth#')) return '/'
  return raw
}

export function Auth() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const hydrated = useAuthStore((state) => state.hydrated)
  const login = useAuthStore((state) => state.login)
  const register = useAuthStore((state) => state.register)
  const loading = useAuthStore((state) => state.loading)
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    if (hydrated && user) navigate(next, { replace: true })
  }, [hydrated, user, next, navigate])

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setFormError(null)
    try {
      if (mode === 'login') await login(username.trim(), password)
      else await register(username.trim(), password, nickname.trim())
      navigate(next, { replace: true })
    } catch (error) {
      setFormError(apiErrorMessage(error))
    }
  }

  const switchMode = (value: Mode) => {
    setMode(value)
    setFormError(null)
  }

  const fillDemo = () => {
    setMode('login')
    setUsername('demo')
    setPassword('demo123')
    setFormError(null)
  }

  return (
    <div className="page-pad mx-auto grid min-h-[calc(100dvh-9rem)] max-w-[1200px] items-center gap-10 py-8 lg:grid-cols-[0.9fr_1.1fr]">
      <div className="relative hidden h-[68vh] min-h-[480px] overflow-hidden rounded-[32px] border border-white/12 lg:block">
        <ImageWithFallback
          src="/static/images/hero/hero-2.webp"
          alt="衣见本季造型"
          className="h-full w-full object-cover"
          loading="eager"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-ink-950/92 via-ink-950/20 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 p-8">
          <p className="eyebrow mb-3">PRIVATE WARDROBE</p>
          <p className="display text-4xl leading-tight text-ivory">
            你的衣橱，
            <br />
            比你自己更懂你。
          </p>
          <p className="mt-4 max-w-sm text-sm leading-7 text-ivory/55">
            登录后，五位智能体的每一次推荐、AI 助理的每一笔订单，都会安静地收进你的档案。
          </p>
        </div>
      </div>

      <div className="mx-auto w-full max-w-md">
        <div className="mb-8">
          <p className="eyebrow mb-3">YIJIAN ATELIER</p>
          <h1 className="display text-[clamp(2.6rem,5vw,4rem)] leading-none text-ivory">
            {mode === 'login' ? '欢迎回来' : '建立你的衣橱'}
          </h1>
          <p className="mt-3 text-sm text-ivory/55">
            {mode === 'login' ? '继续上次未完成的挑选。' : '只需一分钟，让 AI 认识你。'}
          </p>
        </div>

        <div className="mb-6 flex rounded-full border border-white/10 bg-white/[0.03] p-1" role="group" aria-label="登录或注册">
          {(['login', 'register'] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => switchMode(item)}
              aria-pressed={mode === item}
              className={cn(
                'flex-1 rounded-full py-2.5 text-xs tracking-[0.14em] transition',
                mode === item ? 'bg-champagne text-ink-950' : 'text-ivory/55 hover:text-ivory',
              )}
            >
              {item === 'login' ? '登录' : '注册'}
            </button>
          ))}
        </div>

        <GlassPanel strong className="rounded-[28px] p-6 md:p-8">
          <form onSubmit={onSubmit} className="space-y-4">
            <GlassInput
              label="用户名"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              icon={<UserRound className="h-4 w-4" />}
              placeholder="2–32 个字符"
              autoComplete="username"
              required
              minLength={2}
              maxLength={32}
            />
            {mode === 'register' && (
              <GlassInput
                label="昵称（选填）"
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                placeholder="想让 AI 怎么称呼你"
                autoComplete="nickname"
                maxLength={32}
              />
            )}
            <GlassInput
              label="密码"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              icon={<KeyRound className="h-4 w-4" />}
              placeholder="至少 6 位"
              hint={mode === 'register' ? '6–64 位字符，请妥善保管。' : undefined}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
              minLength={6}
              maxLength={64}
            />

            {formError && (
              <p role="alert" className="rounded-xl border border-ember/20 bg-ember/5 px-3 py-2 text-xs leading-6 text-ember">
                {formError}
              </p>
            )}

            <GlassButton
              type="submit"
              variant="primary"
              size="lg"
              className="w-full"
              loading={loading}
              icon={<ArrowRight className="h-4 w-4" />}
            >
              {mode === 'login' ? '进入衣橱' : '创建账号'}
            </GlassButton>
          </form>

          <div className="my-5 flex items-center gap-3">
            <span className="h-px flex-1 bg-white/8" />
            <span className="text-[9px] uppercase tracking-[0.2em] text-ivory/55">Demo</span>
            <span className="h-px flex-1 bg-white/8" />
          </div>
          <button
            type="button"
            onClick={fillDemo}
            className="flex w-full items-center justify-center gap-2 rounded-full border border-champagne/20 bg-champagne/5 py-2.5 text-xs text-champagne/90 transition hover:bg-champagne/10"
          >
            <Sparkles className="h-3.5 w-3.5" /> 使用演示账号 demo / demo123
          </button>
        </GlassPanel>
        <p className="mt-5 text-center text-[10px] leading-5 text-ivory/55">
          未登录也可以浏览衣橱；购物袋、订单与 AI 造型室需要登录后使用。
        </p>
      </div>
    </div>
  )
}

export default Auth
