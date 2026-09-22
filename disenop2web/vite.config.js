import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// BASE_PATH lets each environment serve the app from a different sub-path
// (e.g. "/" in production, "/test/" in the test environment) without
// needing a different vite.config.js per server.
export default defineConfig({
  // /test/ is required on the staging server (page is served at /test/).
  // Production can still override with BASE_PATH=/
  base: process.env.BASE_PATH || '/test/',
  plugins: [react()],
})
