/**
 * MCP JSON-RPC client — used by the Tool Explorer for direct gateway calls
 * and by the clientToolHandler for local gateway tool execution.
 *
 * For local gateways the browser calls the gateway directly.
 * For admin/remote gateways the call is proxied through the backend
 * (the gateway URL may only be reachable from the backend container).
 */

import { api } from '../../core/api/client'
import type { McpToolDefinition } from './types'

let requestId = 0

function nextId(): number {
  return ++requestId
}

// ── Backend-proxied calls (admin / remote gateways) ──────────────────

export async function mcpProxyToolsList(
  gatewayId: string,
): Promise<{ tools: McpToolDefinition[] }> {
  const body = await api.get<{ tools: McpToolDefinition[] }>(
    `/api/mcp/gateways/${encodeURIComponent(gatewayId)}/tools`,
  )
  return { tools: body.tools ?? [] }
}

export async function mcpProxyToolsCall(
  gatewayId: string,
  toolName: string,
  args: Record<string, unknown>,
): Promise<{ stdout: string; error: string | null }> {
  return api.post<{ stdout: string; error: string | null }>(
    `/api/mcp/gateways/${encodeURIComponent(gatewayId)}/call`,
    { tool_name: toolName, arguments: args },
  )
}

// ── Direct calls (local gateways) ───────────────────────────────────

export async function mcpToolsList(
  gatewayUrl: string,
  apiKey: string | null,
  timeoutMs: number = 10_000,
): Promise<{ tools: McpToolDefinition[]; errors: Array<{ server: string; error: string }> }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', id: nextId(), method: 'tools/list' }),
      signal: controller.signal,
    })
    const body = await resp.json()
    if (body.error) {
      throw new Error(body.error.message || JSON.stringify(body.error))
    }
    const result = body.result || {}
    return {
      tools: result.tools || [],
      errors: result._errors || [],
    }
  } finally {
    clearTimeout(timer)
  }
}

export async function mcpToolsCall(
  gatewayUrl: string,
  apiKey: string | null,
  toolName: string,
  args: Record<string, unknown>,
  timeoutMs: number = 30_000,
): Promise<{ stdout: string; error: string | null }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: nextId(),
        method: 'tools/call',
        params: { name: toolName, arguments: args },
      }),
      signal: controller.signal,
    })
    const body = await resp.json()

    if (body.error) {
      return { stdout: '', error: `MCP error: ${body.error.message || JSON.stringify(body.error)}` }
    }

    const result = body.result || {}
    if (result.isError) {
      const text = (result.content || [])
        .filter((c: { type: string }) => c.type === 'text')
        .map((c: { text?: string }) => c.text || '')
        .join('\n')
      return { stdout: '', error: text || 'Tool returned an error' }
    }

    const text = (result.content || [])
      .filter((c: { type: string }) => c.type === 'text')
      .map((c: { text?: string }) => c.text || '')
      .join('\n')
    return { stdout: text, error: null }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      return { stdout: '', error: `MCP gateway timed out after ${timeoutMs}ms` }
    }
    return { stdout: '', error: `MCP gateway unreachable: ${e instanceof Error ? e.message : String(e)}` }
  } finally {
    clearTimeout(timer)
  }
}
