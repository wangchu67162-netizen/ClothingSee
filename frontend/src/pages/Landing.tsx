import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Camera,
  Check,
  ChevronDown,
  ImagePlus,
  Sparkles,
  Store,
  Wand2,
} from 'lucide-react'
import { PageDeck, type DeckSection } from '@/components/layout/PageDeck'
import ProductCard from '@/components/product/ProductCard'
import { AgentCard } from '@/components/ai'
import { AGENT_META, AGENT_ORDER } from '@/components/ai/agents'
import { GlassButton, GlassPanel, ImageWithFallback } from '@/components/ui'
import { api } from '@/lib/api'
import { formatPrice } from '@/lib/format'
import type { Product, ProductList } from '@/types'

interface RoundLine {
  id: string
  status: 'idle' | 'thinking' | 'done' | 'revised'
  score?: number
  lastMessage: string
}

const ROUNDTABLE: RoundLine[] = [
  {
    id: 'fashion',
    status: 'done',
    score: 8.9,
    lastMessage: '落肩风衣的松弛廓形与今年秋冬的趋势一致，品类完整度也够。',
  },
  {
    id: 'art',
    status: 'done',
    score: 8.4,
    lastMessage: '雾灰与香槟金撞出层次，袖口的肌理值得再放大看。',
  },
  {
    id: 'aesthetics',
    status: 'revised',
    score: 9.1,
    lastMessage: '听完价格智能体的预算提醒，我把这套的分数从 8.6 调到 9.1。',
  },
  {
    id: 'price',
    status: 'done',
    score: 8.2,
    lastMessage: '整套 2,198 元，落在这个预算内，替代款还能再省 300。',
  },
  {
    id: 'comfort',
    status: 'thinking',
    lastMessage: '正在核对羊毛混纺的贴肤度、透气性与护理成本…',
  },
]

const FALLBACK_LOOKS = [
  { name: '暮色长风衣', note: '精纺羊毛 · 落肩廓形', image: '/static/images/products/ys-ow-001.webp' },
  { name: '云缎真丝衬衫', note: '桑蚕丝 · 微光泽', image: '/static/images/products/ys-tp-001.webp' },
  { name: '墨影吊带长裙', note: '垂坠 · 夜间造型', image: '/static/images/products/ys-dr-001.webp' },
  { name: '流云阔腿裤', note: '高腰 · 通勤', image: '/static/images/products/ys-bt-001.webp' },
]

const ASSISTANT_LOOKS = [
  { name: '暮色长风衣', price: 1299, image: '/static/images/products/ys-ow-001.webp' },
  { name: '雾金短夹克', price: 899, image: '/static/images/products/ys-ow-002.webp' },
  { name: '山岚羊绒大衣', price: 2399, image: '/static/images/products/ys-ow-003.webp' },
]

const BROWSER_STEPS = [
  '打开云裳商城，搜索「风衣」',
  '点开商品，选择 M 码 / 雾灰',
  '填写收货信息，提交结算',
  '下单成功 · YJ202611211930',
]

function SectionScroll({ children }: { children: ReactNode }) {
  return (
    <div data-deck-scroll="true" className="h-full min-h-0 overflow-y-auto overscroll-contain">
      <div className="mx-auto flex min-h-full w-full max-w-[1440px] flex-col justify-center py-2">{children}</div>
    </div>
  )
}

export function Landing() {
  const [featured, setFeatured] = useState<Product[]>([])
  const [collectionLoading, setCollectionLoading] = useState(true)
  const [collectionFailed, setCollectionFailed] = useState(false)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const primary = await api.get<ProductList>('/products?featured=true&page_size=4', { auth: false })
        let items = primary.items ?? []
        if (items.length < 4) {
          try {
            const more = await api.get<ProductList>('/products?sort=new&page_size=4', { auth: false })
            const seen = new Set(items.map((product) => product.id))
            items = [...items, ...more.items.filter((product) => !seen.has(product.id))].slice(0, 4)
          } catch {
            /* 主列表已可用，补位失败不影响展示 */
          }
        }
        if (alive) setFeatured(items.slice(0, 4))
      } catch {
        if (alive) setCollectionFailed(true)
      } finally {
        if (alive) setCollectionLoading(false)
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [])

  const sections: DeckSection[] = [
    {
      id: 'chapter-hero',
      label: '序章',
      content: (
        <SectionScroll>
          <div className="grid w-full items-center gap-8 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="relative z-10">
              <p className="eyebrow mb-5">AI ATELIER · 2026 秋冬</p>
              <h1 className="display text-balance text-[clamp(3rem,8.4vw,7.8rem)] leading-[0.92] text-ivory">
                把想象，
                <br />
                <span className="bg-gradient-to-r from-ivory via-champagne to-ivory bg-clip-text text-transparent">
                  穿在身上
                </span>
              </h1>
              <p className="mt-6 max-w-md text-[14px] leading-8 text-ivory/55">
                视觉小模型读懂你的照片，五位 AI 智能体围坐共议——从版型、色彩、预算到体感，替你挑出真正的这一件。
              </p>
              <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                <Link to="/stylist" className="w-full sm:w-auto">
                  <GlassButton
                    variant="primary"
                    size="lg"
                    className="w-full sm:w-auto"
                    icon={<Wand2 className="h-4 w-4" />}
                  >
                    开启 AI 造型室
                  </GlassButton>
                </Link>
                <Link to="/shop" className="w-full sm:w-auto">
                  <GlassButton size="lg" className="w-full sm:w-auto" icon={<ArrowRight className="h-4 w-4" />}>
                    逛本季衣橱
                  </GlassButton>
                </Link>
              </div>

              <div className="mt-8 grid max-w-md grid-cols-3 gap-4 border-t border-white/8 pt-5">
                {[
                  ['5 位', '智能体两轮互评'],
                  ['256 维', '视觉小模型检索'],
                  ['真实', '浏览器无头下单'],
                ].map(([value, label]) => (
                  <div key={label}>
                    <p className="display text-xl text-champagne/90">{value}</p>
                    <p className="mt-0.5 text-[9px] leading-4 tracking-[0.1em] text-ivory/55">{label}</p>
                  </div>
                ))}
              </div>

              <div className="mt-6 flex items-center gap-2 text-[9px] uppercase tracking-[0.24em] text-ivory/55">
                <ChevronDown className="h-3.5 w-3.5 animate-bounce" />
                向下滚动 · 进入本季衣橱
              </div>

              <div className="mt-6 overflow-hidden rounded-2xl border border-white/10 lg:hidden">
                <ImageWithFallback
                  src="/static/images/hero/hero-1.webp"
                  alt="衣见本季视觉"
                  loading="eager"
                  className="h-40 w-full object-cover object-top opacity-85"
                />
              </div>
            </div>

            <div className="relative hidden h-[58vh] min-h-[420px] max-h-[620px] lg:block">
              <div className="absolute right-0 top-0 h-[80%] w-[80%] overflow-hidden rounded-[30px] border border-white/12 shadow-glass">
                <ImageWithFallback
                  src="/static/images/hero/hero-1.webp"
                  alt="衣见本季精选"
                  loading="eager"
                  className="h-full w-full object-cover"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-ink-950/60 via-transparent to-transparent" />
                {/* 遮住素材图左上角烧录的旧水印，保证界面标签干净可读 */}
                <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-ink-950/95 via-ink-950/65 to-transparent" />
                <span className="absolute left-4 top-4 rounded-full border border-white/20 bg-black/35 px-3 py-1 text-[9px] tracking-[0.24em] text-ivory/85 backdrop-blur">
                  EDITORIAL 01
                </span>
              </div>
              <div className="animate-float absolute bottom-1 left-0 w-[44%] overflow-hidden rounded-[24px] border border-white/14 shadow-2xl">
                <ImageWithFallback
                  src="/static/images/hero/hero-2.webp"
                  alt="本季穿搭提案"
                  className="aspect-[3/4] w-full object-cover"
                />
              </div>
              <GlassPanel sheen className="absolute -left-5 bottom-[30%] hidden w-52 rounded-2xl p-4 xl:block">
                <p className="eyebrow text-[8px]">VISION · 256D</p>
                <p className="mt-2 text-[11px] leading-5 text-ivory/55">
                  切比雪夫距离检索相似款，真实面料与廓形优先。
                </p>
                <div className="mt-3 flex gap-1">
                  {[0.2, 0.42, 0.66, 0.9].map((width) => (
                    <span key={width} className="h-0.5 rounded-full bg-champagne/60" style={{ width: `${width * 40}px` }} />
                  ))}
                </div>
              </GlassPanel>
              <div className="absolute -right-2 bottom-6 rounded-full border border-champagne/25 bg-black/35 px-3 py-1.5 text-[9px] tracking-[0.18em] text-champagne/90 backdrop-blur">
                16 件本季单品
              </div>
            </div>
          </div>
        </SectionScroll>
      ),
    },
    {
      id: 'chapter-collection',
      label: '本季精选',
      content: (
        <SectionScroll>
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <p className="eyebrow mb-2">CURATED · 墨与金</p>
              <h2 className="display text-[clamp(2.2rem,4.8vw,4.4rem)] leading-none text-ivory">本季衣橱</h2>
              <p className="mt-3 max-w-md text-xs leading-6 text-ivory/55">
                编辑部从 16 件本季单品中挑出四件，作为这一季的起点。
              </p>
            </div>
            <Link
              to="/shop"
              className="group hidden shrink-0 items-center gap-2 text-[10px] tracking-[0.18em] text-ivory/55 transition hover:text-champagne md:flex"
            >
              查看全部 <ArrowRight className="h-3.5 w-3.5 transition group-hover:translate-x-1" />
            </Link>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-5">
            {featured.length > 0
              ? featured.map((product) => <ProductCard key={product.id} product={product} />)
              : collectionLoading
                ? Array.from({ length: 4 }).map((_, index) => (
                    <div
                      key={index}
                      className="aspect-[3/4] animate-pulse rounded-[22px] border border-white/6 bg-white/[0.025]"
                    />
                  ))
                : FALLBACK_LOOKS.map((look) => (
                    <Link
                      key={look.name}
                      to="/shop"
                      className="group overflow-hidden rounded-[22px] border border-white/10 bg-ink-800/60 focus-visible:outline-offset-[-4px]"
                    >
                      <div className="aspect-[3/4] overflow-hidden">
                        <ImageWithFallback
                          src={look.image}
                          alt={look.name}
                          className="h-full w-full object-cover transition duration-700 group-hover:scale-[1.045]"
                        />
                      </div>
                      <div className="p-3">
                        <p className="truncate text-[13px] text-ivory/85">{look.name}</p>
                        <p className="mt-0.5 truncate text-[10px] text-ivory/55">{look.note}</p>
                      </div>
                    </Link>
                  ))}
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[10px] leading-5 text-ivory/55">
              {collectionFailed ? '商品数据暂未同步，先看看编辑部的本季选品。' : '所有商品图均为本地素材，演示不依赖外部 CDN。'}
            </p>
            <Link to="/shop" className="inline-flex items-center gap-1.5 text-[10px] tracking-[0.16em] text-champagne/90 transition hover:text-champagne">
              进入完整目录 <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
        </SectionScroll>
      ),
    },
    {
      id: 'chapter-assistant',
      label: '购物助理',
      content: (
        <SectionScroll>
          <div className="grid w-full items-center gap-8 lg:grid-cols-[0.88fr_1.12fr]">
            <div>
              <p className="eyebrow mb-3">CONCIERGE · 单智能体</p>
              <h2 className="display text-[clamp(2.3rem,5vw,4.8rem)] leading-[0.98] text-ivory">
                一句话，
                <br />
                衣橱为你而动
              </h2>
              <p className="mt-5 max-w-sm text-[13px] leading-7 text-ivory/55">
                告诉它你想买什么，它会给出带图的商品链接；说「帮我下单」，它会打开无头浏览器，替你搜索、选码、结算，并把每一步截图带回来。
              </p>
              <ul className="mt-5 space-y-2.5">
                {[
                  { icon: <Bot className="h-3.5 w-3.5" />, text: '意图识别：找商品 / 直接下单 / 闲聊' },
                  { icon: <Store className="h-3.5 w-3.5" />, text: '内置云裳商城，稳定选择器 + 模拟支付' },
                  { icon: <Camera className="h-3.5 w-3.5" />, text: '逐步截图取证，成功才显示订单号' },
                ].map((item) => (
                  <li key={item.text} className="flex items-center gap-2.5 text-[11px] text-ivory/55">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-champagne/80">
                      {item.icon}
                    </span>
                    {item.text}
                  </li>
                ))}
              </ul>
              <Link to="/assistant" className="mt-6 inline-block">
                <GlassButton variant="ember" icon={<Bot className="h-4 w-4" />}>
                  进入购物助理
                </GlassButton>
              </Link>
            </div>

            <GlassPanel strong className="relative overflow-hidden rounded-[28px] p-4 md:p-5">
              <div className="flex items-center justify-between border-b border-white/8 pb-3.5">
                <div className="flex items-center gap-3">
                  <span className="relative flex h-9 w-9 items-center justify-center rounded-full bg-ember/15 text-ember">
                    <Bot className="h-4 w-4" />
                    <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-sage shadow-[0_0_10px_rgba(110,139,134,.8)]" />
                  </span>
                  <div>
                    <p className="text-[13px] text-ivory">衣见购物助理</p>
                    <p className="text-[9px] tracking-[0.18em] text-ivory/55">BROWSER AGENT · ONLINE</p>
                  </div>
                </div>
                <span className="rounded-full border border-sage/30 bg-sage/10 px-2.5 py-1 text-[8px] tracking-[0.16em] text-sage">
                  无头模式
                </span>
              </div>

              <div className="space-y-2.5 py-4">
                <div className="ml-auto w-fit max-w-[82%] rounded-2xl rounded-br-md bg-champagne/12 px-3.5 py-2 text-[12px] text-ivory/85">
                  我想买一件适合秋天的风衣
                </div>
                <div className="w-fit max-w-[92%] rounded-2xl rounded-bl-md border border-white/8 bg-white/[0.04] px-3.5 py-2.5">
                  <p className="text-[12px] leading-6 text-ivory/70">为你找到 3 件带图链接，先看这一组：</p>
                  <div className="mt-2 grid grid-cols-3 gap-1.5">
                    {ASSISTANT_LOOKS.map((look) => (
                      <div key={look.name} className="overflow-hidden rounded-lg border border-white/8 bg-black/25">
                        <ImageWithFallback src={look.image} alt={look.name} className="aspect-[3/4] w-full object-cover" />
                        <div className="px-1.5 py-1">
                          <p className="truncate text-[8px] text-ivory/70">{look.name}</p>
                          <p className="text-[8px] text-champagne/80">{formatPrice(look.price)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="ml-auto w-fit max-w-[82%] rounded-2xl rounded-br-md bg-champagne/12 px-3.5 py-2 text-[12px] text-ivory/85">
                  帮我下单暮色长风衣，M 码
                </div>

                <div className="space-y-1.5 rounded-2xl border border-white/8 bg-black/20 p-3">
                  {BROWSER_STEPS.map((label, index) => {
                    const done = index < BROWSER_STEPS.length - 1
                    const success = index === BROWSER_STEPS.length - 1
                    return (
                      <div key={label} className="flex items-center gap-2.5 text-[10px]">
                        <span
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                            success ? 'bg-sage/20 text-sage' : done ? 'bg-white/6 text-ivory/55' : 'bg-white/6 text-ivory/55'
                          }`}
                        >
                          {success ? <Check className="h-3 w-3" /> : index + 1}
                        </span>
                        <span className={success ? 'text-sage' : 'text-ivory/55'}>{label}</span>
                        {index === 2 && <ImagePlus className="ml-auto h-2.5 w-2.5 text-ivory/55" />}
                      </div>
                    )
                  })}
                </div>

                <div className="flex items-center gap-2 rounded-full border border-white/8 bg-black/25 px-3.5 py-2 text-[10px] text-ivory/55">
                  <Sparkles className="h-3 w-3 text-champagne/70" />
                  试着说：「我想买真丝衬衫」/「帮我下单阔腿裤」
                </div>
              </div>
              <p className="border-t border-white/8 pt-2.5 text-[9px] leading-5 text-ivory/55">
                云裳商城为内置模拟商城，不连接真实电商与真实支付。
              </p>
            </GlassPanel>
          </div>
        </SectionScroll>
      ),
    },
    {
      id: 'chapter-roundtable',
      label: '五智圆桌',
      content: (
        <SectionScroll>
          <div className="mb-6 text-center">
            <p className="eyebrow mb-2.5">THE ROUND TABLE</p>
            <h2 className="display text-[clamp(2.1rem,4.6vw,4.2rem)] leading-none text-ivory">
              五位智能体，共议一件衣裳
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-[12px] leading-6 text-ivory/55">
              上传一张照片，它们会看见彼此的观点、向具名同伴发问、修正评分，最后交出一套完整的穿搭提案。
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
            {AGENT_ORDER.map((agentId) => {
              const meta = AGENT_META[agentId]
              const line = ROUNDTABLE.find((item) => item.id === agentId)
              return (
                <AgentCard
                  key={agentId}
                  agentId={agentId}
                  name={meta.name}
                  role={meta.role}
                  color={meta.color}
                  score={line?.score}
                  status={line?.status ?? 'idle'}
                  lastMessage={line?.lastMessage}
                />
              )
            })}
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-[1.35fr_0.65fr]">
            <GlassPanel className="rounded-2xl p-4">
              <p className="text-[12px] leading-6 text-ivory/65">
                「审美智能体 → 价格智能体：你的预算提醒让我把这套的分数从 8.6 调到 9.1。」
              </p>
              <p className="mt-1.5 text-[9px] tracking-[0.14em] text-ivory/55">
                Round 2 · 具名互评 · 每位智能体最多修订 2 个分数
              </p>
            </GlassPanel>
            <div className="flex items-center justify-center gap-3">
              <Link to="/stylist">
                <GlassButton variant="primary" icon={<Camera className="h-4 w-4" />}>
                  上传照片，开始共议
                </GlassButton>
              </Link>
            </div>
          </div>
        </SectionScroll>
      ),
    },
    {
      id: 'chapter-closing',
      label: '进入衣橱',
      content: (
        <SectionScroll>
          <div className="relative overflow-hidden rounded-[32px] border border-white/10 px-5 py-10 md:px-12 md:py-14">
            <ImageWithFallback
              src="/static/images/hero/hero-3.webp"
              alt="衣见本季大片"
              className="absolute inset-0 h-full w-full object-cover opacity-30"
            />
            <div className="absolute inset-0 bg-gradient-to-b from-ink-950/75 via-ink-950/55 to-ink-950/90" />
            <div className="relative flex flex-col items-center text-center">
              <p className="eyebrow mb-5">YIJIAN ATELIER · PRIVATE WARDROBE</p>
              <h2 className="display text-balance text-[clamp(2.6rem,6.4vw,6rem)] leading-[0.95] text-ivory">
                让每一次选择，
                <br />
                <span className="text-champagne">都更接近你自己</span>
              </h2>
              <p className="mt-5 max-w-lg text-[12px] leading-7 text-ivory/55">
                小模型负责理解与检索，大模型负责共情与表达。技术退到幕后，你只需要说出想要的感觉。
              </p>
              <div className="mt-7 flex w-full max-w-md flex-col justify-center gap-3 sm:w-auto sm:max-w-none sm:flex-row sm:flex-wrap">
                <Link to="/auth" className="w-full sm:w-auto">
                  <GlassButton
                    variant="primary"
                    size="lg"
                    className="w-full sm:w-auto"
                    icon={<Wand2 className="h-4 w-4" />}
                  >
                    进入我的衣橱
                  </GlassButton>
                </Link>
                <Link to="/stylist" className="w-full sm:w-auto">
                  <GlassButton size="lg" className="w-full sm:w-auto" icon={<Camera className="h-4 w-4" />}>
                    直接体验五智造型
                  </GlassButton>
                </Link>
              </div>
              <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[9px] uppercase tracking-[0.22em] text-ivory/55">
                <span>Vision Retrieval</span>
                <span className="h-1 w-1 rounded-full bg-champagne/40" />
                <span>NLP Knowledge Graph</span>
                <span className="h-1 w-1 rounded-full bg-champagne/40" />
                <span>Qwen Multimodal</span>
                <span className="h-1 w-1 rounded-full bg-champagne/40" />
                <span>Playwright Agent</span>
              </div>
              <div className="mt-7 flex flex-wrap items-center justify-center gap-3 text-[10px] text-ivory/55">
                <span>演示账号 demo / demo123</span>
                <span className="h-3 w-px bg-white/10" />
                <a
                  href="/demo-mall/"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 transition hover:text-champagne"
                >
                  逛逛云裳商城 <ArrowUpRight className="h-3 w-3" />
                </a>
              </div>
              <p className="mt-4 text-[9px] leading-5 text-ivory/55">
                课程演示项目 · 模拟支付 · 所有素材均为本地资源
              </p>
            </div>
          </div>
        </SectionScroll>
      ),
    },
  ]

  return <PageDeck sections={sections} />
}

export default Landing
