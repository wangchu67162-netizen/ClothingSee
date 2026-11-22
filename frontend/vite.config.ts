import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

const backend = 'http://127.0.0.1:8000'

/** 开发与预览共用同一组后端代理，避免 preview 模式下 API/静态资源 404 */
const proxy = {
  '/api': { target: backend, changeOrigin: true },
  '/demo-mall': { target: backend, changeOrigin: true },
  '/static': { target: backend, changeOrigin: true },
  '/screenshots': { target: backend, changeOrigin: true },
  '/uploads': { target: backend, changeOrigin: true },
  '/docs': { target: backend, changeOrigin: true },
  '/openapi.json': { target: backend, changeOrigin: true },
  '/redoc': { target: backend, changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy,
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    target: 'es2020',
    cssCodeSplit: true,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'state-vendor': ['zustand'],
        },
      },
    },
  },
})
