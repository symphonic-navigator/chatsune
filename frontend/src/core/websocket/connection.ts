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

function wsUrl(): string {
  const env = import.meta.env.VITE_WS_URL
  if (env) return env
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${proto}//${window.location.host}`
}

export function connect() {
  const token = useAuthStore.getState().accessToken
  if (!token) return

  intentionalClose = false
  const { setStatus, lastSequence } = useEventStore.getState()
  setStatus("connecting")

  let url = `${wsUrl()}/ws?token=${encodeURIComponent(token)}`
  if (lastSequence) {
    url += `&since=${encodeURIComponent(lastSequence)}`
  }

  ws = new WebSocket(url)

  ws.onopen = () => {
    reconnectDelay = INITIAL_RECONNECT_DELAY
    useEventStore.getState().setStatus("connected")
  }

  ws.onmessage = (msg) => {
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

  ws.onclose = (ev) => {
    useEventStore.getState().setStatus("disconnected")
    ws = null

    if (!intentionalClose && ev.code !== 4001 && ev.code !== 4003) {
      scheduleReconnect()
    }

    if (ev.code === 4001) {
      // Invalid token — try refresh
      handleTokenRefresh()
    }

    if (ev.code === 4003) {
      // Must change password — auth store handles redirect
    }
  }

  ws.onerror = () => {
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
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY)
    connect()
  }, reconnectDelay)
}

async function handleTokenRefresh() {
  try {
    const res = await authApi.refresh()
    useAuthStore.getState().setToken(res.access_token)
    // Reconnect with new token
    disconnect()
    intentionalClose = false
    connect()
  } catch {
    useAuthStore.getState().clear()
  }
}
