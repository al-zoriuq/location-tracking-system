import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  preview: {
    host: true,
    allowedHosts: [
      'marcelamgps.duckdns.org',
      'tauficgps.duckdns.org',
      'sthefanygps.duckdns.org',
      'albagps.duckdns.org',
      // agrega aquí el cuarto dominio del grupo
    ],
  },
})
