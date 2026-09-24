import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  plugins: [react()],
  // Dev only (npm run dev): forward /api to the local Flask backend, so the
  // frontend keeps using relative URLs exactly like behind NGINX in production
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:5001',
    },
  },
})
