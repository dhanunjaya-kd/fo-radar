import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Tailwind reads tailwind.config.js once when the dev server starts, so after pulling a change to it
// (e.g. the light-theme palette) the running server keeps serving the OLD colours -- dark page, white
// cards, invisible text. Restart the dev server automatically whenever that file changes.
const restartOnTailwindConfig = () => ({
  name: 'restart-on-tailwind-config',
  configureServer(server) {
    server.watcher.on('change', (file) => {
      if (/tailwind\.config\.(js|cjs|mjs|ts)$/.test(file)) server.restart()
    })
  },
})

export default defineConfig({
  plugins: [react(), restartOnTailwindConfig()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
