import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8001',
      '/ws': { target: 'ws://localhost:8001', ws: true },
      // Phase 9.8 W A2 — uploaded avatars are served by the backend's
      // StaticFiles mount at /uploads/avatars/{user_id}/{128|48}.jpg.
      '/uploads': 'http://localhost:8001',
    },
  },
})
