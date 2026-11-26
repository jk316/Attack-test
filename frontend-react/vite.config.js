import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // 生产构建的静态资源挂在 FastAPI 的 /static 下，与 backend/server.py 的
  // app.mount("/static", StaticFiles(directory=frontend-react/dist)) 对齐。
  base: '/static/',
  plugins: [react()],
  server: {
    port: 5173,
    // 后端 Plan 1 就绪后，开发环境把 REST/WS 代理到 FastAPI（端口 8000）
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true }
    }
  }
})
