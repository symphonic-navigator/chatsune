import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { useNotificationStore } from "../../core/store/notificationStore"
import { useEventStore } from "../../core/store/eventStore"
import { useMcpStore } from "./mcpStore"
import { sendMessage } from "../../core/websocket/connection"
import { mcpToolsList } from "./mcpClient"
import type { BaseEvent } from "../../core/types/events"
import { Topics } from "../../core/types/events"

interface McpGatewayErrorPayload {
  gateway_name: string
  error: string
  recoverable: boolean
}

interface McpGatewayToolEntry {
  namespace: string
  tier: 'admin' | 'remote' | 'local'
  tools: Array<{ name: string; description: string; server_name: string }>
  collisions: string[]
}

interface McpToolsRegisteredPayload {
  session_id: string
  gateways: McpGatewayToolEntry[]
  total_tools: number
}

/**
 * Discover tools from all enabled local gateways and register them with
 * the backend via WebSocket so they are available during inference.
 */
async function registerLocalGateways(): Promise<void> {
  const gateways = useMcpStore.getState().localGateways
  const localEntries: Array<{ namespace: string; tier: string; tools: Array<{ name: string; description: string; inputSchema: Record<string, unknown> }> }> = []

  for (const gw of gateways) {
    if (!gw.enabled) continue
    try {
      const { tools } = await mcpToolsList(gw.url, gw.api_key)
      if (tools.length === 0) continue

      // Register with backend so tools are available during inference
      sendMessage({
        type: "mcp.tools.register",
        payload: {
          gateway_id: gw.id,
          name: gw.name,
          tier: "local",
          tools: tools.map((t) => ({
            name: t.name,
            description: t.description,
            parameters: t.inputSchema ?? {},
          })),
        },
      })

      // Collect for local UI display
      localEntries.push({
        namespace: gw.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''),
        tier: "local",
        tools: tools.map((t) => ({
          name: t.name,
          description: t.description,
          server_name: gw.name,
        })),
        collisions: [],
      })
    } catch {
      // Gateway unreachable — skip silently
    }
  }

  if (localEntries.length > 0) {
    // Merge local gateways into session gateways (keep existing admin/remote entries)
    const existing = useMcpStore.getState().sessionGateways.filter((e) => e.tier !== "local")
    useMcpStore.getState().setSessionGateways([...existing, ...localEntries])
  }
}

/**
 * Subscribes to MCP gateway events:
 * - Error events are surfaced as toast notifications.
 * - Tools-registered events populate the session tool store so the UI
 *   can display discovered MCP tools.
 * - On WebSocket connect, local gateway tools are discovered and
 *   registered with the backend.
 *
 * Mount exactly once at the top of the authenticated tree (AppLayout).
 */
export function useMcpEvents() {
  const connectionStatus = useEventStore((s) => s.status)

  // Register local gateways whenever the WebSocket connects
  useEffect(() => {
    if (connectionStatus !== "connected") return
    useMcpStore.getState().loadLocalGateways()
    registerLocalGateways()
  }, [connectionStatus])

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
          server_name: t.server_name ?? gw.namespace,
        })),
        collisions: gw.collisions ?? [],
      }))
      // The event carries the full registry state (all tiers) — replace entirely
      useMcpStore.getState().setSessionGateways(entries)
    })

    return () => {
      unsubError()
      unsubRegistered()
    }
  }, [])
}
