import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000"
const backendWs = backendUrl.replace(/^http/, "ws")

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
})
