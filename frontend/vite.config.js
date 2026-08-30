import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Inside docker-compose the backend is reachable at http://backend:8000.
// The browser talks to the vite dev server, which proxies API paths to it.
const BACKEND = process.env.VITE_BACKEND_URL || 'http://backend:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    watch: { usePolling: true },
    proxy: {
      '/dashboard': { target: BACKEND, changeOrigin: true },
      '/chat': { target: BACKEND, changeOrigin: true },
      '/webhook': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/sessions': { target: BACKEND, changeOrigin: true },
    },
  },
})
