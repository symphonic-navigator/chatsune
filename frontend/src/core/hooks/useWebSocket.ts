import { useEffect, useRef } from "react"
import { useEventStore } from "../store/eventStore"
import { useAuthStore } from "../store/authStore"
import { connect, disconnect, sendPing } from "../websocket/connection"

const PING_INTERVAL = 30_000

export function useWebSocket() {
  const status = useEventStore((s) => s.status)
  const lastSequence = useEventStore((s) => s.lastSequence)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
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

  return { status, lastSequence }
}
