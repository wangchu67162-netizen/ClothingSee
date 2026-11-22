import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, CreditCard, MapPin, RefreshCw, ShieldCheck } from 'lucide-react'
import type { Order } from '@/types'
import { api, apiErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { useCartStore } from '@/store/cart'
import { useToast } from '@/store/toast'
import { GlassButton, GlassInput, GlassPanel, ImageWithFallback, Loader, PriceTag } from '@/components/ui'
import { formatPrice } from '@/lib/format'

interface FieldErrors {
  name?: string
  phone?: string
  address?: string
}

const PHONE_PATTERN = /^[0-9+\-\s]{5,24}$/

export function Checkout() {
  const user = useAuthStore((state) => state.user)
  const cart = useCartStore((state) => state.cart)
  const load = useCartStore((state) => state.load)
  const reset = useCartStore((state) => state.reset)
  const loading = useCartStore((state) => state.loading)
  const cartError = useCartStore((state) => state.error)
  const navigate = useNavigate()
  const toast = useToast()
  const [ready, setReady] = useState(false)
  const [name, setName] = useState(user?.nickname || user?.username || '')
  const [phone, setPhone] = useState('13800000000')
  const [address, setAddress] = useState('上海市徐汇区云裳路 88 号')
  const [note, setNote] = useState('')
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let alive = true
    setReady(false)
    void load().finally(() => {
      if (alive) setReady(true)
    })
    return () => {
      alive = false
    }
  }, [load])

  const retry = () => {
    setReady(false)
    void load().finally(() => setReady(true))
  }

  const clearField = (key: keyof FieldErrors) => {
    setFieldErrors((previous) => ({ ...previous, [key]: undefined }))
  }

  const validate = (): { ok: boolean; values: { name: string; phone: string; address: string } } => {
    const values = { name: name.trim(), phone: phone.trim(), address: address.trim() }
    const nextErrors: FieldErrors = {}
    if (!values.name) nextErrors.name = '请填写收货人姓名'
    else if (values.name.length > 32) nextErrors.name = '收货人姓名不能超过 32 个字符'
    if (!PHONE_PATTERN.test(values.phone)) nextErrors.phone = '请填写有效的联系电话（5–24 位，可含 + - 空格）'
    if (values.address.length < 3) nextErrors.address = '请填写至少 3 个字符的收货地址'
    else if (values.address.length > 256) nextErrors.address = '收货地址不能超过 256 个字符'
    setFieldErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) {
      setSubmitError('请先完善配送信息。')
      return { ok: false, values }
    }
    return { ok: true, values }
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!cart || cart.items.length === 0 || submitting) return
    setSubmitError(null)
    const { ok, values } = validate()
    if (!ok) return

    setSubmitting(true)
    try {
      const order = await api.post<Order>('/orders', {
        shipping: values,
        note: note.trim(),
      })
      reset()
      toast.success('下单成功', `订单号 ${order.order_no} · ${formatPrice(order.total)}（模拟支付）`)
      navigate(`/orders?new=${encodeURIComponent(order.order_no)}`)
    } catch (reason) {
      setSubmitError(apiErrorMessage(reason))
    } finally {
      setSubmitting(false)
    }
  }

  if (!cart) {
    if (ready && cartError) {
      return (
        <div className="page-pad mx-auto max-w-3xl py-24 text-center" role="alert">
          <h1 className="display text-4xl text-ivory">结算台暂时无法读取购物袋</h1>
          <p className="mt-3 text-sm text-ember">{cartError}</p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <GlassButton variant="primary" icon={<RefreshCw className="h-4 w-4" />} onClick={retry}>
              重新加载
            </GlassButton>
            <Link to="/cart">
              <GlassButton>返回购物袋</GlassButton>
            </Link>
          </div>
        </div>
      )
    }
    return (
      <div className="page-pad mx-auto flex min-h-[50vh] max-w-6xl items-center justify-center">
        <Loader label={loading || !ready ? '正在核对购物袋' : '正在打开结算台'} />
      </div>
    )
  }

  if (cart.items.length === 0) {
    return (
      <div className="page-pad mx-auto max-w-3xl py-24 text-center">
        <h1 className="display text-4xl text-ivory">购物袋是空的</h1>
        <p className="mt-3 text-sm text-ivory/55">先挑一件喜欢的衣裳，再来结算。</p>
        <Link to="/shop" className="mt-7 inline-block">
          <GlassButton variant="primary">回到衣橱</GlassButton>
        </Link>
      </div>
    )
  }

  return (
    <div className="page-pad mx-auto max-w-[1120px]">
      <button
        type="button"
        onClick={() => navigate('/cart')}
        className="mb-6 inline-flex items-center gap-2 text-xs tracking-[0.12em] text-ivory/55 transition hover:text-champagne"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 返回购物袋
      </button>
      <div className="mb-8">
        <p className="eyebrow mb-3">CHECKOUT · SIMULATED PAYMENT</p>
        <h1 className="display text-[clamp(2.6rem,5vw,4.6rem)] leading-none text-ivory">结算</h1>
        <p className="mt-3 text-sm text-ivory/55">填写配送信息后提交，订单会记录在你的档案中。</p>
      </div>

      <form onSubmit={onSubmit} noValidate className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <GlassPanel className="rounded-[28px] p-6 md:p-8">
          <div className="mb-6 flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-champagne/10 text-champagne">
              <MapPin className="h-4 w-4" />
            </span>
            <div>
              <p className="text-sm text-ivory">配送信息</p>
              <p className="text-[10px] tracking-[0.16em] text-ivory/55">仅用于课程演示，不会真实发货</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <GlassInput
              label="收货人"
              value={name}
              onChange={(event) => {
                setName(event.target.value)
                clearField('name')
              }}
              error={fieldErrors.name}
              aria-invalid={Boolean(fieldErrors.name)}
              autoComplete="name"
              placeholder="姓名或昵称"
              required
              maxLength={32}
            />
            <GlassInput
              label="手机号"
              type="tel"
              inputMode="tel"
              value={phone}
              onChange={(event) => {
                setPhone(event.target.value)
                clearField('phone')
              }}
              error={fieldErrors.phone}
              aria-invalid={Boolean(fieldErrors.phone)}
              autoComplete="tel"
              placeholder="用于演示联系"
              required
              maxLength={24}
            />
          </div>
          <div className="mt-4">
            <GlassInput
              label="收货地址"
              value={address}
              onChange={(event) => {
                setAddress(event.target.value)
                clearField('address')
              }}
              error={fieldErrors.address}
              aria-invalid={Boolean(fieldErrors.address)}
              autoComplete="street-address"
              placeholder="省 / 市 / 区 / 详细地址"
              required
              maxLength={256}
            />
          </div>
          <div className="mt-4">
            <label className="block">
              <span className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.24em] text-ivory/55">
                <span>订单备注</span>
                <span className="font-normal tracking-[0.08em] text-ivory/55">{note.length}/256</span>
              </span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                className="input-glass min-h-24 resize-none"
                placeholder="尺码建议、包装需求或想对造型师说的话（选填）"
                maxLength={256}
              />
            </label>
          </div>

          <div className="mt-7 flex items-center gap-3 rounded-2xl border border-white/8 bg-white/[0.025] p-4">
            <CreditCard className="h-5 w-5 text-champagne/80" />
            <div className="flex-1">
              <p className="text-sm text-ivory/80">模拟支付</p>
              <p className="text-[11px] text-ivory/55">演示环境不会调用任何真实支付接口</p>
            </div>
            <span className="rounded-full border border-sage/30 bg-sage/10 px-2.5 py-1 text-[9px] tracking-[0.16em] text-sage">
              SAFE DEMO
            </span>
          </div>

          {submitError && (
            <p role="alert" className="mt-4 rounded-2xl border border-ember/20 bg-ember/5 px-4 py-3 text-sm leading-6 text-ember">
              {submitError}
            </p>
          )}

          <GlassButton
            type="submit"
            variant="primary"
            size="lg"
            className="mt-6 w-full"
            loading={submitting}
            disabled={submitting}
            icon={<ShieldCheck className="h-4 w-4" />}
          >
            {submitting ? '正在提交订单…' : '提交订单（模拟支付）'}
          </GlassButton>
        </GlassPanel>

        <GlassPanel strong className="h-fit rounded-[28px] p-6 lg:sticky lg:top-28">
          <p className="eyebrow mb-5">ORDER SUMMARY</p>
          <div className="max-h-[42vh] space-y-3 overflow-y-auto pr-1">
            {cart.items.map((item) => (
              <div key={item.id} className="flex items-center gap-3">
                <ImageWithFallback
                  src={item.product.image}
                  alt=""
                  className="h-14 w-11 rounded-lg object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-ivory/75">{item.product.name}</p>
                  <p className="text-[10px] text-ivory/55">
                    {item.color || '默认色'} · {item.size || '均码'} · ×{item.quantity}
                  </p>
                </div>
                <span className="text-xs text-ivory/55">{formatPrice(item.line_total)}</span>
              </div>
            ))}
          </div>
          <div className="my-5 hairline" />
          <div className="space-y-2 text-xs text-ivory/55">
            <div className="flex justify-between">
              <span>商品小计</span>
              <span>{formatPrice(cart.total_amount)}</span>
            </div>
            <div className="flex justify-between">
              <span>配送</span>
              <span className="text-sage">免运费</span>
            </div>
          </div>
          <div className="mt-4 flex items-end justify-between">
            <span className="text-xs uppercase tracking-[0.18em] text-ivory/55">应付</span>
            <PriceTag price={cart.total_amount} size="lg" />
          </div>
          <p className="mt-4 text-[10px] leading-5 text-ivory/55">
            提交后订单状态为“已支付”，这是课程演示的模拟支付，不会产生任何真实扣款。
          </p>
        </GlassPanel>
      </form>
    </div>
  )
}

export default Checkout
