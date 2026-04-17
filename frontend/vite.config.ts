import { defineConfig, type Plugin } from "vitest/config"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { VitePWA } from "vite-plugin-pwa"

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000"
const backendWs = backendUrl.replace(/^http/, "ws")

// Dark base colour from the design palette; also used as manifest theme/background.
const THEME_COLOUR = "#0a0710"

// Vite's `server.headers` option only applies to a subset of dev-server
// responses — notably it is NOT applied to worker-script chunks served via
// `?worker_file`, which breaks module-workers in a COEP-isolated document.
// Registering our own middleware in `configureServer` guarantees every
// response (including worker chunks) carries the isolation headers.
const crossOriginIsolationHeaders: Plugin = {
  name: "cross-origin-isolation-headers",
  configureServer(server) {
    server.middlewares.use((_req, res, next) => {
      res.setHeader("Cross-Origin-Opener-Policy", "same-origin")
      res.setHeader("Cross-Origin-Embedder-Policy", "credentialless")
      res.setHeader("Cross-Origin-Resource-Policy", "same-origin")
      next()
    })
  },
}

export default defineConfig({
  plugins: [
    crossOriginIsolationHeaders,
    react(),
    tailwindcss(),
    VitePWA({
      // Prompt the user before applying an update — Chatsune shows a toast
      // with a "Reload" action rather than silently refreshing.
      registerType: "prompt",
      strategies: "generateSW",
      injectRegister: null,
      // Keep the SW out of the way during development; it only runs in prod builds.
      devOptions: { enabled: false },
      workbox: {
        // App shell only — no runtime caching of API or WebSocket traffic,
        // as that would break Chatsune's event-first architecture.
        globPatterns: ["**/*.{js,css,html,svg,png,webp,woff2}"],
        // Workers that must NOT be served from the SW cache:
        //  - sandbox.worker: cross-origin-isolated execution relies on fresh
        //    COEP/CORP headers from nginx. A cached SW response carries the
        //    headers it was captured with, so if nginx policy changes (as it
        //    did in cf3095d) existing clients get stuck on stale headers until
        //    they clear site data manually. Bypassing the SW for this worker
        //    avoids that class of bug entirely.
        globIgnores: ["**/sandbox.worker-*.js"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//],
        // Main bundle currently sits just above Workbox's 2 MiB default, which
        // refuses to precache it. Give comfortable headroom; future work can
        // code-split if the bundle keeps growing.
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        cleanupOutdatedCaches: true,
      },
      includeAssets: [
        "favicon.svg",
        "apple-touch-icon.png",
        "pwa/icon.svg",
        "pwa/icon-192.png",
        "pwa/icon-512.png",
        "pwa/icon-512-maskable.png",
      ],
      manifest: {
        name: "Chatsune",
        short_name: "Chatsune",
        description: "A privacy-first, self-hosted AI companion",
        theme_color: THEME_COLOUR,
        background_color: THEME_COLOUR,
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        scope: "/",
        icons: [
          {
            src: "/pwa/icon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "any",
          },
          {
            src: "/pwa/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/pwa/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/pwa/icon-512-maskable.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
    }),
  ],
  optimizeDeps: {
    include: ["@ricky0123/vad-web"],
  },
  server: {
    port: 5173,
    host: true,
    // Cross-origin isolation headers are applied via the
    // `crossOriginIsolationHeaders` plugin above so that they also cover
    // worker-script chunks, which `server.headers` does not reach.
    proxy: {
      "/api": backendUrl,
      "/ws": {
        target: backendWs,
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
  },
})
