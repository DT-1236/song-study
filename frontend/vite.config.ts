import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The API is reached on the app's own origin under /api, as it is when
    // deployed behind a reverse proxy.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
