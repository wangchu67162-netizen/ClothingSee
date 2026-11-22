import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Ban, Bot, PackageCheck, RefreshCw, ShoppingBag, X } from 'lucide-react'
import type { Order } from '@/types'
import { api, apiErrorMessage } from '@/lib/api'
import { GlassButton, GlassPanel, ImageWithFallback, Loader, PriceTag } from '@/components/ui'
import { useToast } from '@/store/toast'
import { formatDate, formatPrice } from '@/lib/format'
import { cn } from '@/lib/cn'

const STATUS: Record<string, { label: string; className: string }> = {
  paid: { label: '已支付', className: 'border-sage/35 bg-sage/10 text-sage' },
  shipped: { label: '配送中', className: 'border-champagne/35 bg-champagne/10 text-champagne' },
  completed: { label: '已完成', className: 'border-white/15 bg-white/5 text-ivory/55' },
  cancelled: { label: '已取消', className: 'border-ember/30 bg-ember/8 text-ember/80' },
}

const UNKNOWN_STATUS = { label: '未知状态', className: 'border-white/15 bg-white/5 text-ivory/55' }

export function Orders() {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cancellingId, setCancellingId] = useState<number | null>(null)
  const [params] = useSearchParams()
  const fresh = params.get('new')
  const [showFresh, setShowFresh] = useState(Boolean(fresh))
  const toast = useToast()

  const loadOrders = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const value = await api.get<Order[]>('/orders')
      setOrders(value)
    } catch (reason) {
      setError(apiErrorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadOrders()
  }, [loadOrders])

  const onCancel = async (order: Order) => {
    if (cancellingId !== null) return
    if (!window.confirm(`确定取消订单 ${order.order_no} 吗？取消后不可恢复。`)) return
    setCancellingId(order.id)
    try {
      const updated = await api.post<Order>(`/orders/${order.id}/cancel`)
      setOrders((previous) => previous.map((item) => (item.id === updated.id ? updated : item)))
      toast.success('订单已取消', updated.order_no)
    } catch (reason) {
      toast.error('取消失败', apiErrorMessage(reason))
    } finally {
      setCancellingId(null)
    }
  }

  return (
    <div className="page-pad mx-auto max-w-[1080px]">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-3">ORDERS · YOUR ARCHIVE</p>
          <h1 className="display text-[clamp(2.6rem,5vw,4.6rem)] leading-none text-ivory">我的订单</h1>
          <p className="mt-3 text-sm text-ivory/55">
            来自平台结算与 AI 购物助理的订单，都会记录在这里。带 AI 标记的订单由云裳商城模拟下单产生。
          </p>
        </div>
        <GlassButton
          size="sm"
          icon={<RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />}
          onClick={() => void loadOrders()}
          disabled={loading}
        >
          {loading ? '刷新中…' : '刷新订单'}
        </GlassButton>
      </div>

      {showFresh && fresh && (
        <GlassPanel className="mb-6 flex flex-wrap items-center gap-3 rounded-2xl border-sage/25 p-4">
          <PackageCheck className="h-5 w-5 shrink-0 text-sage" />
          <p className="min-w-0 flex-1 text-sm text-ivory/70">
            下单成功 · 订单号 <span className="break-all text-champagne">{fresh}</span>
          </p>
          <button
            type="button"
            onClick={() => setShowFresh(false)}
            className="rounded-full p-1.5 text-ivory/55 transition hover:bg-white/8 hover:text-ivory"
            aria-label="关闭下单成功提示"
          >
            <X className="h-4 w-4" />
          </button>
        </GlassPanel>
      )}

      {loading && orders.length === 0 ? (
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader label="正在翻阅订单" />
        </div>
      ) : error && orders.length === 0 ? (
        <div className="glass rounded-3xl p-12 text-center" role="alert">
          <p className="display text-3xl text-ivory/80">订单暂时没有取回来</p>
          <p className="mt-3 text-sm text-ember">{error}</p>
          <GlassButton
            variant="primary"
            className="mt-5"
            icon={<RefreshCw className="h-4 w-4" />}
            onClick={() => void loadOrders()}
          >
            重新加载
          </GlassButton>
        </div>
      ) : orders.length === 0 ? (
        <div className="glass rounded-3xl py-20 text-center">
          <ShoppingBag className="mx-auto h-10 w-10 text-champagne/45" />
          <p className="display mt-5 text-3xl text-ivory/80">还没有订单</p>
          <p className="mt-2 text-sm text-ivory/55">去衣橱挑一件，或者让 AI 助理替你下单。</p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Link to="/shop">
              <GlassButton variant="primary">逛衣橱</GlassButton>
            </Link>
            <Link to="/assistant">
              <GlassButton icon={<Bot className="h-4 w-4" />}>找 AI 助理</GlassButton>
            </Link>
          </div>
        </div>
      ) : (
        <>
          {error && (
            <p role="alert" className="mb-4 rounded-2xl border border-ember/20 bg-ember/5 px-4 py-3 text-xs text-ember">
              {error}（当前展示的是上次加载的订单）
            </p>
          )}
          <div className="space-y-4" aria-live="polite">
            {orders.map((order) => {
              const status = STATUS[order.status] ?? { ...UNKNOWN_STATUS, label: order.status || UNKNOWN_STATUS.label }
              const cancelling = cancellingId === order.id
              return (
                <GlassPanel key={order.id} className="rounded-[24px] p-5 md:p-6">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 pb-4">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span className="text-xs tracking-[0.12em] text-ivory/65">{order.order_no}</span>
                      <span
                        className={cn(
                          'rounded-full border px-2.5 py-1 text-[9px] tracking-[0.14em]',
                          status.className,
                        )}
                      >
                        {status.label}
                      </span>
                      {order.source === 'agent' ? (
                        <span className="flex items-center gap-1 rounded-full border border-ember/25 bg-ember/8 px-2.5 py-1 text-[9px] tracking-[0.12em] text-ember/85">
                          <Bot className="h-3 w-3" /> AI 下单
                        </span>
                      ) : (
                        <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[9px] tracking-[0.12em] text-ivory/55">
                          平台下单
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-[10px] text-ivory/55">{formatDate(order.created_at)}</span>
                      {order.status === 'paid' && (
                        <button
                          type="button"
                          onClick={() => onCancel(order)}
                          disabled={cancellingId !== null}
                          className="flex items-center gap-1 rounded-full border border-white/12 px-2.5 py-1.5 text-[10px] text-ivory/55 transition hover:border-ember/30 hover:text-ember disabled:opacity-40"
                        >
                          <Ban className="h-3 w-3" /> {cancelling ? '取消中…' : '取消订单'}
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 space-y-3">
                    {order.items.map((item) => (
                      <div key={item.id} className="flex items-center gap-3">
                        <ImageWithFallback
                          src={item.image}
                          alt=""
                          className="h-16 w-12 rounded-xl object-cover"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-ivory/80">{item.name}</p>
                          <p className="mt-0.5 text-[11px] text-ivory/55">
                            {item.color || '默认色'} · {item.size || '均码'} · ×{item.quantity}
                          </p>
                        </div>
                        <span className="text-xs text-ivory/55">{formatPrice(item.price)}</span>
                      </div>
                    ))}
                  </div>

                  {order.note && (
                    <p className="mt-4 rounded-2xl border border-white/8 bg-white/[0.02] px-4 py-2.5 text-[11px] leading-5 text-ivory/55">
                      备注：{order.note}
                    </p>
                  )}

                  <div className="mt-4 flex flex-wrap items-end justify-between gap-3 border-t border-white/8 pt-4">
                    <div className="min-w-0 text-[11px] text-ivory/55">
                      <p>
                        收货：{order.shipping_name} · {order.shipping_phone}
                      </p>
                      <p className="mt-0.5 break-all">{order.shipping_address}</p>
                      {order.source === 'agent' && order.external_ref && (
                        <p className="mt-0.5 text-ivory/55">云裳商城单号：{order.external_ref}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] uppercase tracking-[0.16em] text-ivory/55">合计</span>
                      <PriceTag price={order.total} size="md" />
                    </div>
                  </div>
                </GlassPanel>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

export default Orders
