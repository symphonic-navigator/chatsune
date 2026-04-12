import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { useNotificationStore } from "../../core/store/notificationStore"
import type { BaseEvent } from "../../core/types/events"
import { Topics } from "../../core/types/events"

interface McpGatewayErrorPayload {
  gateway_name: string
  error: string
  recoverable: boolean
}

/**
 * Subscribes to MCP gateway error events and surfaces them as toast
 * notifications. Mount exactly once at the top of the authenticated tree
 * (AppLayout). Recoverable errors show as warnings; non-recoverable as errors.
 */
export function useMcpEvents() {
  useEffect(() => {
    const addNotification = useNotificationStore.getState().addNotification

    const unsub = eventBus.on(Topics.MCP_GATEWAY_ERROR, (event: BaseEvent) => {
      const payload = event.payload as McpGatewayErrorPayload
      addNotification({
        level: payload.recoverable ? "warning" : "error",
        title: `MCP: ${payload.gateway_name}`,
        message: payload.error,
      })
    })

    return () => {
      unsub()
    }
  }, [])
}
