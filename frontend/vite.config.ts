import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // API_PROXY_TARGET points /api at another backend, such as the browser
  // harness's test-database one (docs/browser-checks.md).
  const { API_PROXY_TARGET } = loadEnv(mode, '.', 'API_')
  return {
    plugins: [react()],
    server: {
      // The API is reached on the app's own origin under /api, as it is when
      // deployed behind a reverse proxy.
      proxy: {
        '/api': {
          target: API_PROXY_TARGET ?? 'http://localhost:8000',
          // Caddy picks the site by Host, so a remote target needs its own
          // hostname
          changeOrigin: true,
        },
      },
    },
  }
})
