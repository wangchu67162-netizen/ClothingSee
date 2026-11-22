import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Minus, Plus, RefreshCw, ShoppingBag, Trash2 } from 'lucide-react'
import { GlassButton, GlassPanel, ImageWithFallback, Loader, PriceTag } from '@/components/ui'
import { useCartStore } from '@/store/cart'
import { useToast } from '@/store/toast'
import { apiErrorMessage } from '@/lib/api'
import { formatPrice } from '@/lib/format'

export function Cart() {
  const cart = useCartStore((state) => state.cart)
  const loading = useCartStore((state) => state.loading)
  const error = useCartStore((state) => state.error)
  const load = useCartStore((state) => state.load)
  const update = useCartStore((state) => state.update)
  const remove = useCartStore((state) => state.remove)
  const clear = useCartStore((state) => state.clear)
  const toast = useToast()
  const navigate = useNavigate()
  const [ready, setReady] = useState(false)
  const [pendingId, setPendingId] = useState<number | null>(null)
  const [clearing, setClearing] = useState(false)

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

  const change = async (itemId: number, quantity: number) => {
    if (pendingId !== null || clearing) return
    setPendingId(itemId)
    try {
      await update(itemId, quantity)
    } catch (reason) {
      toast.error('更新失败', apiErrorMessage(reason))
    } finally {
      setPendingId(null)
    }
  }

  const onRemove = async (itemId: number) => {
    if (pendingId !== null || clearing) return
    setPendingId(itemId)
    try {
      await remove(itemId)
      toast.info('已从购物袋移除')
    } catch (reason) {
      toast.error('移除失败', apiErrorMessage(reason))
    } finally {
      setPendingId(null)
    }
  }

  const onClear = async () => {
    if (clearing || pendingId !== null) return
    if (!window.confirm('确定清空购物袋吗？已加入的商品会全部移除。')) return
    setClearing(true)
    try {
      await clear()
      toast.info('购物袋已清空')
    } catch (reason) {
      toast.error('清空失败', apiErrorMessage(reason))
    } finally {
      setClearing(false)
    }
  }

  if (!cart && (!ready || loading)) {
    return (
      <div className="page-pad mx-auto flex min-h-[50vh] max-w-6xl items-center justify-center">
        <Loader label="正在打开购物袋" />
      </div>
    )
  }

  if (!cart && error) {
    return (
      <div className="page-pad mx-auto max-w-3xl py-20 text-center" role="alert">
        <p className="display text-4xl text-ivory">购物袋没有打开</p>
        <p className="mt-3 text-sm text-ember">{error}</p>
        <GlassButton variant="primary" className="mt-6" icon={<RefreshCw className="h-4 w-4" />} onClick={retry}>
          重新加载
        </GlassButton>
      </div>
    )
  }

  if (!cart || cart.items.length === 0) {
    return (
      <div className="page-pad mx-auto max-w-3xl py-20 text-center">
        <span className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border border-white/10 bg-white/[0.03]">
          <ShoppingBag className="h-8 w-8 text-champagne/70" />
        </span>
        <h1 className="display mt-7 text-4xl text-ivory">购物袋还是空的</h1>
        <p className="mt-3 text-sm text-ivory/55">去衣橱里逛逛，或者让五智造型室替你挑一套。</p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Link to="/shop">
            <GlassButton variant="primary">逛本季衣橱</GlassButton>
          </Link>
          <Link to="/stylist">
            <GlassButton>AI 造型室</GlassButton>
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page-pad mx-auto max-w-[1200px]">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-3">
            YOUR BAG · {cart.total_quantity} {cart.total_quantity === 1 ? 'ITEM' : 'ITEMS'}
          </p>
          <h1 className="display text-[clamp(2.6rem,5vw,4.8rem)] leading-none text-ivory">购物袋</h1>
        </div>
        <button
          type="button"
          onClick={onClear}
          disabled={clearing || pendingId !== null}
          className="flex items-center gap-1.5 rounded-full border border-white/12 px-3.5 py-2 text-[11px] text-ivory/55 transition hover:border-ember/30 hover:text-ember disabled:opacity-40"
        >
          <Trash2 className="h-3.5 w-3.5" /> {clearing ? '正在清空…' : '清空购物袋'}
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.5fr_0.8fr]">
        <div className="space-y-3">
          {cart.items.map((item) => {
            const busy = pendingId === item.id
            const maxQuantity = item.product.stock > 0 ? Math.min(20, item.product.stock) : 20
            const atStockLimit = item.product.stock > 0 && item.quantity >= item.product.stock
            const lowStock = item.product.stock > 0 && item.product.stock <= 10
            return (
              <GlassPanel key={item.id} className="flex gap-4 rounded-3xl p-3.5 md:p-4">
                <Link
                  to={`/product/${item.product.id}`}
                  className="w-24 shrink-0 overflow-hidden rounded-2xl md:w-28"
                >
                  <ImageWithFallback
                    src={item.product.image}
                    alt={item.product.name}
                    className="aspect-[3/4] w-full object-cover"
                  />
                </Link>
                <div className="flex min-w-0 flex-1 flex-col justify-between py-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        to={`/product/${item.product.id}`}
                        className="block truncate text-[15px] text-ivory transition hover:text-champagne"
                      >
                        {item.product.name}
                      </Link>
                      <p className="mt-1 text-[11px] text-ivory/55">
                        {item.color || '默认色'} · {item.size || '均码'} · {item.product.category}
                      </p>
                      <p className="mt-0.5 text-[10px] text-ivory/55">
                        单价 {formatPrice(item.product.price)}
                        {item.product.original_price &&
                          item.product.original_price > item.product.price && (
                            <span className="ml-1.5 line-through text-ivory/55">
                              {formatPrice(item.product.original_price)}
                            </span>
                          )}
                      </p>
                      {atStockLimit ? (
                        <p className="mt-1 text-[10px] text-ember/90">
                          已达库存上限（{item.product.stock} 件）
                        </p>
                      ) : lowStock ? (
                        <p className="mt-1 text-[10px] text-ember/90">
                          库存仅剩 {item.product.stock} 件
                        </p>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => onRemove(item.id)}
                      disabled={busy || clearing}
                      className="rounded-full p-2 text-ivory/55 transition hover:bg-ember/10 hover:text-ember disabled:opacity-30"
                      aria-label={`移除 ${item.product.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
                    <div className="flex items-center rounded-full border border-white/12">
                      <button
                        type="button"
                        onClick={() => change(item.id, item.quantity - 1)}
                        disabled={busy || item.quantity <= 1}
                        className="p-2 text-ivory/55 transition hover:text-ivory disabled:opacity-30"
                        aria-label={`减少 ${item.product.name} 的数量`}
                      >
                        <Minus className="h-3.5 w-3.5" />
                      </button>
                      <span className="min-w-7 text-center text-xs text-ivory" aria-live="polite">
                        {busy ? '…' : item.quantity}
                      </span>
                      <button
                        type="button"
                        onClick={() => change(item.id, item.quantity + 1)}
                        disabled={busy || item.quantity >= maxQuantity}
                        className="p-2 text-ivory/55 transition hover:text-ivory disabled:opacity-30"
                        aria-label={`增加 ${item.product.name} 的数量`}
                      >
                        <Plus className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <PriceTag price={item.line_total} size="md" />
                  </div>
                </div>
              </GlassPanel>
            )
          })}
        </div>

        <div className="lg:sticky lg:top-28 lg:self-start">
          <GlassPanel strong className="rounded-[28px] p-6">
            <p className="eyebrow mb-5">ORDER SUMMARY</p>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between text-ivory/55">
                <span>商品件数</span>
                <span>{cart.total_quantity}</span>
              </div>
              <div className="flex justify-between text-ivory/55">
                <span>商品小计</span>
                <span>{formatPrice(cart.total_amount)}</span>
              </div>
              <div className="flex justify-between text-ivory/55">
                <span>配送</span>
                <span className="text-sage">模拟免运费</span>
              </div>
            </div>
            <div className="my-5 hairline" />
            <div className="flex items-end justify-between">
              <span className="text-xs uppercase tracking-[0.18em] text-ivory/55">合计</span>
              <PriceTag price={cart.total_amount} size="lg" />
            </div>
            <GlassButton
              variant="primary"
              size="lg"
              className="mt-6 w-full"
              icon={<ArrowRight className="h-4 w-4" />}
              disabled={pendingId !== null || clearing}
              onClick={() => navigate('/checkout')}
            >
              去结算
            </GlassButton>
            <p className="mt-3 text-center text-[10px] tracking-[0.08em] text-ivory/55">
              演示项目 · 不产生真实支付
            </p>
          </GlassPanel>
        </div>
      </div>
    </div>
  )
}

export default Cart
