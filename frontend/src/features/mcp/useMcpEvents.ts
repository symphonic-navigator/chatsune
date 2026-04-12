import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { useNotificationStore } from "../../core/store/notificationStore"
import { useMcpStore } from "./mcpStore"
import type { BaseEvent } from "../../core/types/events"
import { Topics } from "../../core/types/events"

interface McpGatewayErrorPayload {
  gateway_name: string
  error: string
  recoverable: boolean
}

interface McpGatewayToolEntry {
  namespace: string
  tier: string
  tools: Array<{ name: string; description: string }>
}

interface McpToolsRegisteredPayload {
  session_id: string
  gateways: McpGatewayToolEntry[]
  total_tools: number
}

/**
 * Subscribes to MCP gateway events:
 * - Error events are surfaced as toast notifications.
 * - Tools-registered events populate the session tool store so the UI
 *   can display discovered MCP tools.
 *
 * Mount exactly once at the top of the authenticated tree (AppLayout).
 */
export function useMcpEvents() {
  useEffect(() => {
    const addNotification = useNotificationStore.getState().addNotification

    const unsubError = eventBus.on(Topics.MCP_GATEWAY_ERROR, (event: BaseEvent) => {
      const payload = event.payload as unknown as McpGatewayErrorPayload
      addNotification({
        level: payload.recoverable ? "warning" : "error",
        title: `MCP: ${payload.gateway_name}`,
        message: payload.error,
      })
    })

    const unsubRegistered = eventBus.on(Topics.MCP_TOOLS_REGISTERED, (event: BaseEvent) => {
      const payload = event.payload as unknown as McpToolsRegisteredPayload
      const entries = payload.gateways.map((gw) => ({
        namespace: gw.namespace,
        tier: gw.tier,
        tools: gw.tools.map((t) => ({
          name: t.name,
          description: t.description,
          inputSchema: {},
        })),
      }))
      useMcpStore.getState().setSessionTools(entries)
    })

    return () => {
      unsubError()
      unsubRegistered()
    }
  }, [])
}
