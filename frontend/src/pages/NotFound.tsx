import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { GlassButton } from '@/components/ui'

export function NotFound() {
  return (
    <div className="page-pad mx-auto flex min-h-[60vh] max-w-3xl flex-col items-center justify-center text-center">
      <p className="eyebrow mb-4">404 · LOST IN THE ATELIER</p>
      <h1 className="display text-[clamp(4rem,12vw,9rem)] leading-none text-ivory/85">走丢了</h1>
      <p className="mt-4 max-w-md text-sm leading-7 text-ivory/55">
        这一页不在衣橱里。回到首页，或者让五位智能体重新为你指路。
      </p>
      <Link to="/" className="mt-7">
        <GlassButton variant="primary" icon={<ArrowLeft className="h-4 w-4" />}>回到首页</GlassButton>
      </Link>
    </div>
  )
}

export default NotFound
