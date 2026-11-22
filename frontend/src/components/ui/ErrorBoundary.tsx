import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/** 捕获页面渲染异常，避免整站白屏；错误信息只写控制台，不展示隐私内容 */
export class AppErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[衣见] 页面渲染失败：', error.message, info.componentStack)
  }

  private reload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children
    if (this.props.fallback) return this.props.fallback
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-5 py-16" role="alert">
        <div className="glass glass-panel w-full max-w-lg px-7 py-10 text-center">
          <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-ember/25 bg-ember/[0.07] text-ember">
            <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          </span>
          <p className="display text-2xl text-ivory">页面暂时无法显示</p>
          <p className="mt-3 text-sm leading-7 text-ivory/55">
            可能是数据加载或渲染出现异常。刷新页面通常可以恢复；若持续出现，请确认后端服务已启动。
          </p>
          <button type="button" className="btn-glass mt-7 h-11 px-6" onClick={this.reload}>
            重新加载页面
          </button>
        </div>
      </div>
    )
  }
}

export default AppErrorBoundary
