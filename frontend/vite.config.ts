import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { VitePWA } from "vite-plugin-pwa"

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000"
const backendWs = backendUrl.replace(/^http/, "ws")

// Dark base colour from the design palette; also used as manifest theme/background.
const THEME_COLOUR = "#0a0710"

export default defineConfig({
  plugins: [
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
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//],
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
    exclude: ["onnxruntime-web", "@ricky0123/vad-web"],
  },
  server: {
    port: 5173,
    host: true,
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
