import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Backend is reached through a same-origin proxy: cookies and CSRF work as in production.
// Origin is passed through unchanged (no changeOrigin) — the backend checks it against ALLOWED_ORIGINS.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_PROXY_TARGET || 'http://localhost:8000'
  return {
    define: { 'import.meta.env.VITE_API_MODE': JSON.stringify(env.VITE_API_MODE === 'mock' ? 'mock' : 'real') },
    plugins: [react()],
    base: mode === 'mock' ? './' : '/',
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target },
        '/health': { target },
      },
    },
    build: { outDir: mode === 'mock' ? 'dist-demo' : 'dist', sourcemap: false },
  }
})
