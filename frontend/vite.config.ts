import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: {
    // Budget for the lazy-loaded Three.js constellation chunk (~571 kB today).
    // Anything larger is a regression worth investigating.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      input: {
        console: fileURLToPath(new URL('./index.html', import.meta.url)),
        site: fileURLToPath(new URL('./site/index.html', import.meta.url)),
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
