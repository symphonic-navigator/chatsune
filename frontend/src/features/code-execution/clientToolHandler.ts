/* clientToolHandler.ts — bridges the WebSocket event bus to the
 * sandbox host. Registered once at app startup; the returned cleanup
 * function is the unsubscribe callback supplied by eventBus.on.
 */

import type { BaseEvent } from '../../core/types/events'
import { eventBus } from '../../core/websocket/eventBus'
import { sendMessage } from '../../core/websocket/connection'
import { runSandbox } from './sandboxHost'
import { mcpToolsCall } from '../mcp/mcpClient'
import { useMcpStore } from '../mcp/mcpStore'
import { getAllPlugins } from '../integrations/registry'
import { useIntegrationsStore } from '../integrations/store'

const MAX_OUTPUT_BYTES = 4096

interface DispatchPayload {
  session_id: string
  tool_call_id: string
  tool_name: string
  arguments: { code?: string } & Record<string, unknown>
  timeout_ms: number
  target_connection_id: string
}

function sendResult(
  toolCallId: string,
  result: { stdout: string; error: string | null },
): void {
  sendMessage({
    type: 'chat.client_tool.result',
    tool_call_id: toolCallId,
    result,
  })
}

export function registerClientToolHandler(): () => void {
  return eventBus.on('chat.client_tool.dispatch', (event: BaseEvent) => {
    // eventBus callbacks are sync — we start the async work but do not
    // await it here. The handler sends the result via sendMessage when
    // the sandbox resolves.
    void handleDispatch(event.payload as unknown as DispatchPayload)
  })
}

async function handleDispatch(ev: DispatchPayload): Promise<void> {
  // Check if this is an integration plugin tool (e.g. lovense_get_toys → plugin 'lovense')
  const integrationResult = await tryIntegrationDispatch(ev)
  if (integrationResult) return

  // Check if this is an MCP tool (contains __ separator)
  if (ev.tool_name.includes('__')) {
    await handleMcpDispatch(ev)
    return
  }

  if (ev.tool_name !== 'calculate_js') {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Unknown client tool: ${ev.tool_name}`,
    })
    return
  }

  const code = typeof ev.arguments?.code === 'string' ? ev.arguments.code : ''
  if (!code) {
    sendResult(ev.tool_call_id, { stdout: '', error: 'No code provided' })
    return
  }

  try {
    const result = await runSandbox(code, ev.timeout_ms, MAX_OUTPUT_BYTES)
    sendResult(ev.tool_call_id, result)
  } catch (e) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Sandbox host crashed: ${e instanceof Error ? e.message : String(e)}`,
    })
  }
}

/** Try to route a tool call to an integration plugin. Returns true if handled. */
async function tryIntegrationDispatch(ev: DispatchPayload): Promise<boolean> {
  const plugins = getAllPlugins()
  for (const [pluginId, plugin] of plugins) {
    if (!plugin.executeTool) continue
    const prefix = pluginId + '_'
    if (!ev.tool_name.startsWith(prefix)) continue

    console.debug('[integration-dispatch] matched plugin=%s tool=%s', pluginId, ev.tool_name)

    // Verify the integration is usable for this user. We check
    // `effective_enabled` rather than `enabled` because linked premium
    // integrations (xai_voice, mistral_voice) carry a meaningless stored
    // `enabled=false` — see backend/modules/integrations/_handlers.py.
    const config = useIntegrationsStore.getState().getConfig(pluginId)
    if (!config?.effective_enabled) {
      console.warn('[integration-dispatch] plugin=%s is not effectively enabled', pluginId)
      sendResult(ev.tool_call_id, {
        stdout: '',
        error: `Integration '${pluginId}' is not enabled`,
      })
      return true
    }

    console.debug('[integration-dispatch] executing tool=%s config=%o args=%o', ev.tool_name, config.config, ev.arguments)
    try {
      const output = await plugin.executeTool(ev.tool_name, ev.arguments, config.config)
      console.debug('[integration-dispatch] tool=%s result=%s', ev.tool_name, output.slice(0, 200))
      sendResult(ev.tool_call_id, { stdout: output, error: null })
    } catch (e) {
      console.error('[integration-dispatch] tool=%s error:', ev.tool_name, e)
      sendResult(ev.tool_call_id, {
        stdout: '',
        error: `Integration tool failed: ${e instanceof Error ? e.message : String(e)}`,
      })
    }
    return true
  }
  return false
}

async function handleMcpDispatch(ev: DispatchPayload): Promise<void> {
  const separatorIdx = ev.tool_name.indexOf('__')
  const namespace = ev.tool_name.substring(0, separatorIdx)
  const originalToolName = ev.tool_name.substring(separatorIdx + 2)

  // Find the local gateway for this namespace
  const localGateways = useMcpStore.getState().localGateways
  const gateway = localGateways.find((gw) => {
    const normalised = gw.name.toLowerCase().replace(/[^a-z0-9]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '')
    return normalised === namespace
  })

  if (!gateway) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `No local MCP gateway found for namespace '${namespace}'`,
    })
    return
  }

  try {
    const result = await mcpToolsCall(
      gateway.url,
      gateway.api_key,
      originalToolName,
      ev.arguments as Record<string, unknown>,
      ev.timeout_ms,
    )
    sendResult(ev.tool_call_id, result)
  } catch (e) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `MCP call failed: ${e instanceof Error ? e.message : String(e)}`,
    })
  }
}
