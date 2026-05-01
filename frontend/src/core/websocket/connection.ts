import type { BaseEvent } from "../types/events"
import { eventBus } from "./eventBus"
import { useEventStore } from "../store/eventStore"
import { useAuthStore } from "../store/authStore"
import { forceLogout } from "../auth/logoutCoordinator"
import { refreshToken as refreshAccessToken } from "../api/client"

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000
const PONG_TIMEOUT_MS = 10_000

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectDelay = INITIAL_RECONNECT_DELAY
let intentionalClose = false
let pongTimer: ReturnType<typeof setTimeout> | null = null

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

      if (data.type === "pong") {
        if (pongTimer) {
          clearTimeout(pongTimer)
          pongTimer = null
        }
        return
      }

      if (data.type === "token.expiring_soon") {
        void handleTokenRefresh()
        return
      }

      if (data.type === "ws.hello") {
        if (typeof data.connection_id === "string") {
          useEventStore.getState().setConnectionId(data.connection_id)
        }
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

    if (pongTimer) {
      clearTimeout(pongTimer)
      pongTimer = null
    }

    useEventStore.getState().setStatus("disconnected")
    useEventStore.getState().setConnectionId(null)
    ws = null

    if (ev.code === 4003) {
      void forceLogout(
        "must_change_password",
        "Bitte ändere dein Passwort, um fortzufahren.",
      )
      return
    }

    if (ev.code === 4001) {
      void handleTokenRefresh()
      return
    }

    if (!intentionalClose) {
      scheduleReconnect()
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
  if (pongTimer) {
    clearTimeout(pongTimer)
    pongTimer = null
  }
  ws?.close()
  ws = null
  useEventStore.getState().setStatus("disconnected")
  useEventStore.getState().setConnectionId(null)
}

/**
 * Check whether the WebSocket is currently healthy and reconnect if not.
 *
 * Called on `visibilitychange` when the tab becomes visible again. Mobile
 * browsers (especially iOS Safari) may silently let a backgrounded WebSocket
 * rot without firing `onclose` — so the client only finds out at the next
 * failed ping (up to 30 s later). Forcing a fresh connect on resume closes
 * that gap. Sequence-based catchup via `?since=<lastSequence>` covers any
 * events missed while the tab was in the background.
 *
 * Cheap no-op when the socket is already OPEN.
 */
export function ensureConnected() {
  if (intentionalClose) return
  if (!useAuthStore.getState().accessToken) return
  if (ws && ws.readyState === WebSocket.OPEN) return
  // connect() disarms any stale socket and reconnects cleanly
  connect()
}

export function sendPing() {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }))
    // Arm a timeout: if no pong arrives within PONG_TIMEOUT_MS the socket is
    // dead but the browser hasn't noticed. Force-close so the existing
    // reconnect logic engages.
    if (pongTimer) clearTimeout(pongTimer)
    pongTimer = setTimeout(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(1000, "pong timeout")
      }
    }, PONG_TIMEOUT_MS)
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

async function handleTokenRefresh(): Promise<void> {
  try {
    const outcome = await refreshAccessToken()
    if (outcome === "ok") {
      // Token refreshed; reconnect with the new token.
      scheduleReconnect()
      return
    }
    if (outcome === "backend_unavailable") {
      // Health monitor will surface the backend-down state. Do NOT log
      // the user out for a transient backend hiccup.
      scheduleReconnect()
      return
    }
    // outcome === "auth_failed": the backend authoritatively rejected
    // the refresh. End the session.
    void forceLogout(
      "session_expired",
      "Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.",
    )
  } catch {
    // Unexpected error — keep trying via the reconnect loop.
    scheduleReconnect()
  }
}
