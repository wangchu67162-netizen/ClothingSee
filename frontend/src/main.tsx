import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles/globals.css'

const container = document.getElementById('root')

if (!container) {
  throw new Error('未找到应用挂载节点 #root')
}

// 本地内联 favicon：避免浏览器请求 /favicon.ico 时产生 404，也不引入外链资源
if (!document.querySelector('link[rel="icon"]')) {
  const mark =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
    '<rect width="64" height="64" rx="14" fill="#07070b"/>' +
    '<path d="M20 18l12 8 12-8" fill="none" stroke="#d8be93" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M32 26v22" stroke="#d8be93" stroke-width="3" stroke-linecap="round"/>' +
    '<circle cx="32" cy="48" r="3" fill="#f0ddbb"/>' +
    '</svg>'
  const favicon = document.createElement('link')
  favicon.rel = 'icon'
  favicon.type = 'image/svg+xml'
  favicon.href = `data:image/svg+xml,${encodeURIComponent(mark)}`
  document.head.appendChild(favicon)
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
