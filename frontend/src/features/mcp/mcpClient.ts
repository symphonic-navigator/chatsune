/**
 * MCP JSON-RPC client — used by the Tool Explorer for direct gateway calls
 * and by the clientToolHandler for local gateway tool execution.
 *
 * For local gateways the browser calls the gateway directly.
 * For admin/remote gateways the call is proxied through the backend
 * (the gateway URL may only be reachable from the backend container).
 */

import packageJson from '../../../package.json'
import { api } from '../../core/api/client'
import { useMcpStore } from './mcpStore'
import type { McpToolDefinition } from './types'

export const MCP_PROTOCOL_VERSION = '2025-06-18'
export const APP_VERSION = (packageJson as { version: string }).version

type JsonRpcReply = {
  jsonrpc: string
  id?: number
  result?: unknown
  error?: { code: number; message: string }
}

export async function readJsonRpcResponse(resp: Response, expectedId?: number): Promise<JsonRpcReply> {
  const ctype = (resp.headers.get('content-type') || '').split(';')[0].trim().toLowerCase()

  if (ctype === 'application/json') {
    return (await resp.json()) as JsonRpcReply
  }
  if (ctype === 'text/event-stream') {
    if (!resp.body) throw new Error('SSE response has no body')
    const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value
      let nl: number
      while ((nl = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, nl).replace(/\r$/, '')
        buffer = buffer.slice(nl + 1)
        if (!line.startsWith('data:')) continue
        const data = line.slice(5).trimStart()
        if (!data) continue
        try {
          const obj = JSON.parse(data) as JsonRpcReply
          if (expectedId === undefined || obj.id === expectedId) return obj
        } catch {
          // malformed — skip, keep reading
        }
      }
    }
    throw new Error('SSE stream closed without matching response')
  }
  throw new Error(`Unexpected content-type from MCP gateway: ${ctype}`)
}

let requestId = 0

function nextId(): number {
  return ++requestId
}

// ── Session lifecycle ─────────────────────────────────────────────────

async function doInitialise(url: string, apiKey: string | null): Promise<string | null> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
  }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  const initId = nextId()
  const initResp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: initId,
      method: 'initialize',
      params: {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: 'chatsune', version: APP_VERSION },
      },
    }),
  })
  if (!initResp.ok) {
    throw new Error(`MCP initialise failed: HTTP ${initResp.status}`)
  }
  const sessionId = initResp.headers.get('mcp-session-id')
  // Drain body — for SSE we want to consume up to the matching reply,
  // for JSON we just discard.
  try {
    await readJsonRpcResponse(initResp, initId)
  } catch {
    // Stream may close without a strict match; the session id header is
    // what we need from this step.
  }

  const notifHeaders = { ...headers }
  if (sessionId) notifHeaders['Mcp-Session-Id'] = sessionId
  await fetch(url, {
    method: 'POST',
    headers: notifHeaders,
    body: JSON.stringify({
      jsonrpc: '2.0',
      method: 'notifications/initialized',
    }),
  })

  return sessionId
}

export async function ensureSession(
  gatewayUrl: string,
  apiKey: string | null,
): Promise<string | null> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const store = useMcpStore.getState()
  const existing = store.getSession(url)

  if (existing && existing.sessionId !== undefined) return existing.sessionId
  if (existing?.initialising) return existing.initialising

  const initPromise = doInitialise(url, apiKey)
  useMcpStore.setState((s) => ({
    sessions: {
      ...s.sessions,
      [url]: { sessionId: undefined, initialising: initPromise },
    },
  }))

  try {
    const sessionId = await initPromise
    store.setSession(url, sessionId)
    return sessionId
  } catch (e) {
    store.clearSession(url)
    throw e
  }
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

  let sessionId: string | null
  try {
    sessionId = await ensureSession(gatewayUrl, apiKey)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    throw new Error(`MCP initialise failed: ${msg}`)
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
  }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
  if (sessionId) headers['Mcp-Session-Id'] = sessionId

  const resp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ jsonrpc: '2.0', id: nextId(), method: 'tools/list' }),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!resp.ok) {
    if (resp.status === 404 && sessionId) {
      useMcpStore.getState().clearSession(url)
    }
    throw new Error(`MCP tools/list failed: HTTP ${resp.status}`)
  }
  const body = await readJsonRpcResponse(resp)
  if (body.error) {
    throw new Error(body.error.message || JSON.stringify(body.error))
  }
  const result = (body.result || {}) as {
    tools?: McpToolDefinition[]
    _errors?: Array<{ server: string; error: string }>
  }
  return {
    tools: result.tools || [],
    errors: result._errors || [],
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

  let sessionId: string | null
  try {
    sessionId = await ensureSession(gatewayUrl, apiKey)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return { stdout: '', error: `MCP initialise failed: ${msg}` }
  }

  const doCall = async (sid: string | null): Promise<Response> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
    }
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
    if (sid) headers['Mcp-Session-Id'] = sid

    return fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: nextId(),
        method: 'tools/call',
        params: { name: toolName, arguments: args },
      }),
      signal: AbortSignal.timeout(timeoutMs),
    })
  }

  let resp: Response
  try {
    resp = await doCall(sessionId)
    if (resp.status === 404 && sessionId) {
      useMcpStore.getState().clearSession(url)
      try {
        sessionId = await ensureSession(gatewayUrl, apiKey)
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        return { stdout: '', error: `MCP re-initialise failed: ${msg}` }
      }
      resp = await doCall(sessionId)
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      return { stdout: '', error: `MCP gateway timed out after ${timeoutMs}ms` }
    }
    const msg = e instanceof Error ? e.message : String(e)
    return { stdout: '', error: `MCP gateway unreachable: ${msg}` }
  }

  if (!resp.ok) {
    return { stdout: '', error: `MCP gateway returned HTTP ${resp.status}` }
  }

  let body: { jsonrpc: string; id?: number; result?: unknown; error?: { code: number; message: string } }
  try {
    body = await readJsonRpcResponse(resp)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return { stdout: '', error: `MCP gateway response read failed: ${msg}` }
  }

  if (body.error) {
    return { stdout: '', error: `MCP error: ${body.error.message || JSON.stringify(body.error)}` }
  }

  const result = (body.result || {}) as { isError?: boolean; content?: Array<{ type: string; text?: string }> }
  if (result.isError) {
    const text = (result.content || [])
      .filter((c) => c.type === 'text')
      .map((c) => c.text || '')
      .join('\n')
    return { stdout: '', error: text || 'Tool returned an error' }
  }

  const text = (result.content || [])
    .filter((c) => c.type === 'text')
    .map((c) => c.text || '')
    .join('\n')
  return { stdout: text, error: null }
}
