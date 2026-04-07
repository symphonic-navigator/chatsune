import type { BaseEvent } from "../types/events"
import { eventBus } from "./eventBus"
import { useEventStore } from "../store/eventStore"
import { useAuthStore } from "../store/authStore"
import { authApi } from "../api/auth"

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectDelay = INITIAL_RECONNECT_DELAY
let intentionalClose = false
let currentRefresh: Promise<boolean> | null = null

function wsUrl(): string {
  const env = import.meta.env.VITE_WS_URL
  if (env) return env
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${proto}//${window.location.host}`
}

export function connect() {
  const token = useAuthStore.getState().accessToken
  if (!token) return

  // Disarm and close any existing connection to prevent orphaned sockets
  // (React StrictMode double-mounts can race with async onclose)
  if (ws) {
    ws.onopen = null
    ws.onmessage = null
    ws.onclose = null
    ws.onerror = null
    ws.close()
    ws = null
  }

  intentionalClose = false
  const { setStatus, lastSequence } = useEventStore.getState()
  setStatus("connecting")

  let url = `${wsUrl()}/ws?token=${encodeURIComponent(token)}`
  if (lastSequence !== null) {
    url += `&since=${encodeURIComponent(lastSequence)}`
  }

  const socket = new WebSocket(url)
  ws = socket

  socket.onopen = () => {
    if (ws !== socket) return
    reconnectDelay = INITIAL_RECONNECT_DELAY
    useEventStore.getState().setStatus("connected")
  }

  socket.onmessage = (msg) => {
    if (ws !== socket) return
    try {
      const data = JSON.parse(msg.data)

      if (data.type === "pong") return

      if (data.type === "token.expiring_soon") {
        handleTokenRefresh()
        return
      }

      const event = data as BaseEvent
      if (event.sequence) {
        useEventStore.getState().setLastSequence(event.sequence)
      }
      eventBus.emit(event)
    } catch {
      // Ignore malformed messages
    }
  }

  socket.onclose = (ev) => {
    if (ws !== socket) return
    useEventStore.getState().setStatus("disconnected")
    ws = null

    if (!intentionalClose && ev.code !== 4001 && ev.code !== 4003) {
      scheduleReconnect()
    }

    if (ev.code === 4001) {
      handleTokenRefresh()
    }
  }

  socket.onerror = () => {
    // onclose will fire after onerror, reconnect handled there
  }
}

export function disconnect() {
  intentionalClose = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  ws?.close()
  ws = null
  useEventStore.getState().setStatus("disconnected")
}

export function sendPing() {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }))
  }
}

export function sendMessage(message: Record<string, unknown>) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message))
  }
}

function scheduleReconnect() {
  useEventStore.getState().setStatus("reconnecting")
  // Apply ±20% jitter to spread reconnect storms
  const jitter = reconnectDelay * (Math.random() * 0.4 - 0.2)
  const delay = Math.max(0, reconnectDelay + jitter)
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY)
    connect()
  }, delay)
}

async function handleTokenRefresh(): Promise<boolean> {
  // Share the in-flight refresh promise so parallel callers wait on the same request
  if (currentRefresh) return currentRefresh
  currentRefresh = (async () => {
    try {
      const res = await authApi.refresh()
      useAuthStore.getState().setToken(res.access_token)
      disconnect()
      intentionalClose = false
      connect()
      return true
    } catch {
      useAuthStore.getState().clear()
      return false
    } finally {
      currentRefresh = null
    }
  })()
  return currentRefresh
}
