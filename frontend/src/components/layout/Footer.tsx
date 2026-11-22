import { Link } from 'react-router-dom'

export function Footer() {
  return (
    <footer className="relative z-10 border-t border-white/8 bg-ink-950/70 px-6 py-12 backdrop-blur-sm md:px-12">
      <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <p className="display text-3xl tracking-[0.12em] text-ivory">衣见 ATELIER</p>
          <p className="mt-3 max-w-sm text-sm leading-7 text-ivory/55">
            把想象，穿在身上。由视觉小模型、语言知识图谱与五位 AI 智能体共同完成的私人衣橱。
          </p>
          <p className="mt-5 text-[10px] uppercase tracking-[0.32em] text-champagne/70">AI · Fashion · Curation</p>
        </div>
        <nav aria-label="页脚导航" className="text-sm text-ivory/55">
          <p className="mb-3 text-[10px] uppercase tracking-[0.28em] text-ivory/55">探索</p>
          <Link to="/shop" className="block py-1 transition hover:text-ivory">本季衣橱</Link>
          <Link to="/stylist" className="block py-1 transition hover:text-ivory">五智造型室</Link>
          <Link to="/assistant" className="block py-1 transition hover:text-ivory">AI 购物助理</Link>
          <Link to="/orders" className="block py-1 transition hover:text-ivory">我的订单</Link>
        </nav>
        <div className="text-sm text-ivory/55">
          <p className="mb-3 text-[10px] uppercase tracking-[0.28em] text-ivory/55">说明</p>
          <p className="py-1">课程项目 · 模拟支付</p>
          <p className="py-1">云裳商城为内置演示站点</p>
          <p className="py-1">商品图仅作教学演示</p>
          <a
            href="/docs"
            target="_blank"
            rel="noreferrer"
            className="block py-1 transition hover:text-ivory"
            aria-label="打开后端 API 文档（新窗口）"
          >
            API 文档
          </a>
        </div>
      </div>
      <div className="mx-auto mt-10 flex max-w-6xl flex-col gap-2 border-t border-white/6 pt-5 text-[10px] tracking-[0.16em] text-ivory/55 sm:flex-row sm:items-center sm:justify-between">
        <span>© {new Date().getFullYear()} 衣见 ATELIER · 服装平台课程项目</span>
        <span>视觉小模型 + NLP-KG · Qwen 多模态 · Playwright 无头浏览器</span>
      </div>
    </footer>
  )
}

export default Footer
