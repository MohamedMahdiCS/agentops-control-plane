// GitHub Pages build: only the public landing page, served from the
// repository path. The deploy workflow moves site/index.html to the root.
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  base: '/agentops-control-plane/',
  build: {
    outDir: 'dist-pages',
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      input: { site: fileURLToPath(new URL('./site/index.html', import.meta.url)) },
    },
  },
})
