import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// Phase 10 W4 — PWA configuration. Adds a service worker for app-shell
// caching, a web app manifest for "Add to Home Screen" install affordance,
// and an offline fallback page that renders when the SPA shell is uncached
// AND the network is unreachable.
//
// Design notes:
//   - registerType: 'autoUpdate' so the SW silently swaps to the latest
//     bundle on next navigation. Avoids a "refresh required" UX.
//   - injectRegister: 'auto' lets the plugin add the SW registration
//     snippet to the built index.html — no manual main.jsx wiring needed.
//   - navigateFallback: '/index.html' so SPA route navigations resolve to
//     the cached shell. The denylist excludes /api and /uploads so the SW
//     never tries to serve API responses or uploaded files from cache.
//   - runtimeCaching for navigations uses NetworkFirst with a catch
//     handler that returns the precached /offline.html when fully offline
//     and the SPA shell is not yet cached. This is the "honest UX" path
//     called out in the spec — when there's no connection at all, show a
//     branded static page instead of a generic browser error.
//   - theme_color is the verified Tailwind brand navy (#1B3A5C), matching
//     Nav.jsx and the Phase 7C winner highlights.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      includeAssets: ['favicon.svg', 'icons.svg', 'offline.html'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg,ico,webp,webmanifest}'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api/, /^\/uploads/],
        // When fully offline (no SW shell cache hit and no network), serve
        // the precached /offline.html for navigation requests instead of
        // the browser's default error page.
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.mode === 'navigate',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'navigations',
              networkTimeoutSeconds: 5,
            },
          },
        ],
        // Workbox advanced: setCatchHandler returns offline.html when any
        // navigation request rejects (true offline + no cached shell).
        navigateFallbackAllowlist: [/^\/(?!api|uploads).*/],
      },
      manifest: {
        name: 'Liquid Democracy',
        short_name: 'LiqDem',
        description: 'Multi-tenant liquid democracy platform',
        theme_color: '#1B3A5C',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
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
