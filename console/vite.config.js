import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发时 /api 与 /api/ws 都代理到 ArgOS 后端（127.0.0.1:8766），
// 所以前端代码里永远用相对路径，不写死端口。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8766',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
