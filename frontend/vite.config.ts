import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendPort = process.env.BACKEND_PORT || '8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        // Full close-screen can scan hundreds of names; avoid premature proxy cutoffs.
        timeout: 300_000,
        proxyTimeout: 300_000,
      },
    },
  },
})
