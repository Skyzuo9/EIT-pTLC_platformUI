import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期把 /api 代理到 FastAPI 后端 (uvicorn :18080)
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',                // 钉死 IPv4: 默认 'localhost' 在本机仅落 IPv6([::1]), 浏览器走 IPv4 时拒连(ERR_CONNECTION_REFUSED)
    port: 15173,
    strictPort: true,                 // 15173 被占直接报错, 不静默漂移到 15174, 与 launcher 固定端口契约一致
    proxy: {
      // REST + WebSocket 都代理到 FastAPI 后端; 目标用 127.0.0.1 而非 localhost: 后端 uvicorn 仅监听 IPv4, 避免 node 把 localhost 解析成 ::1 导致代理 ECONNREFUSED
      '/api': { target: 'http://127.0.0.1:18080', ws: true, changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const path = id.replace(/\\/g, '/')
          if (
            path.includes('node_modules/three/') ||
            path.includes('node_modules/three-mesh-bvh/')
          ) return 'three'
          if (
            path.includes('node_modules/postprocessing/') ||
            path.includes('node_modules/camera-controls/')
          ) return 'postfx'
        },
      },
    },
    chunkSizeWarningLimit: 1500,
  },
})
