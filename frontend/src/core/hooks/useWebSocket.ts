import { useEffect, useRef } from "react"
import { useEventStore } from "../store/eventStore"
import { useAuthStore } from "../store/authStore"
import { connect, disconnect, ensureConnected, sendPing } from "../websocket/connection"

const PING_INTERVAL = 30_000

export function useWebSocket() {
  const status = useEventStore((s) => s.status)
  const lastSequence = useEventStore((s) => s.lastSequence)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (pingRef.current) {
      clearInterval(pingRef.current)
      pingRef.current = null
    }

    if (isAuthenticated) {
      connect()
      pingRef.current = setInterval(sendPing, PING_INTERVAL)
    }

    return () => {
      if (pingRef.current) {
        clearInterval(pingRef.current)
        pingRef.current = null
      }
      disconnect()
    }
  }, [isAuthenticated])

  // Reconnect on tab resume. Mobile browsers (iOS Safari in particular) may
  // silently let a backgrounded WebSocket rot without firing onclose; forcing
  // a health check on `visibilitychange` closes that gap. Also covers laptop
  // lid-close on desktop, which has the same symptom.
  useEffect(() => {
    if (!isAuthenticated) return

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        ensureConnected()
      }
    }

    const handleFocus = () => {
      ensureConnected()
    }

    document.addEventListener("visibilitychange", handleVisibilityChange)
    window.addEventListener("focus", handleFocus)

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange)
      window.removeEventListener("focus", handleFocus)
    }
  }, [isAuthenticated])

  return { status, lastSequence }
}
