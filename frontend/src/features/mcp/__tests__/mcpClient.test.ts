import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mcpToolsList, mcpToolsCall } from '../mcpClient'

describe('mcpClient — Streamable HTTP Accept header', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue({
      json: async () => ({ jsonrpc: '2.0', id: 1, result: { tools: [] } }),
    })
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('mcpToolsList sends Accept: application/json, text/event-stream', async () => {
    await mcpToolsList('http://example.com', null)
    expect(fetchSpy).toHaveBeenCalledOnce()
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const accept = (init.headers as Record<string, string>)['Accept'] ?? ''
    expect(accept).toContain('application/json')
    expect(accept).toContain('text/event-stream')
  })

  it('mcpToolsCall sends Accept: application/json, text/event-stream', async () => {
    fetchSpy.mockResolvedValue({
      json: async () => ({
        jsonrpc: '2.0',
        id: 1,
        result: { content: [{ type: 'text', text: 'ok' }] },
      }),
    })
    await mcpToolsCall('http://example.com', null, 'ping', {})
    expect(fetchSpy).toHaveBeenCalledOnce()
    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const accept = (init.headers as Record<string, string>)['Accept'] ?? ''
    expect(accept).toContain('application/json')
    expect(accept).toContain('text/event-stream')
  })
})

describe('readJsonRpcResponse', () => {
  it('parses a JSON response', async () => {
    const resp = new Response(JSON.stringify({ jsonrpc: '2.0', id: 7, result: 'x' }), {
      headers: { 'content-type': 'application/json' },
    })
    const { readJsonRpcResponse } = await import('../mcpClient')
    const out = await readJsonRpcResponse(resp)
    expect(out.id).toEqual(7)
    expect(out.result).toEqual('x')
  })

  it('parses an SSE response and matches by id', async () => {
    const sseBody =
      `data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"x":1}}\n\n` +
      `data: {"jsonrpc":"2.0","id":42,"result":"hit"}\n\n`
    const resp = new Response(sseBody, {
      headers: { 'content-type': 'text/event-stream' },
    })
    const { readJsonRpcResponse } = await import('../mcpClient')
    const out = await readJsonRpcResponse(resp, 42)
    expect(out.id).toEqual(42)
    expect(out.result).toEqual('hit')
  })

  it('throws on SSE close without matching id', async () => {
    const resp = new Response(`data: {"jsonrpc":"2.0","id":1,"result":"a"}\n\n`, {
      headers: { 'content-type': 'text/event-stream' },
    })
    const { readJsonRpcResponse } = await import('../mcpClient')
    await expect(readJsonRpcResponse(resp, 999)).rejects.toThrow(/SSE stream closed/)
  })

  it('throws on unexpected content-type', async () => {
    const resp = new Response('hello', { headers: { 'content-type': 'text/plain' } })
    const { readJsonRpcResponse } = await import('../mcpClient')
    await expect(readJsonRpcResponse(resp)).rejects.toThrow(/Unexpected content-type/)
  })
})

describe('ensureSession', () => {
  let fetchSpy: ReturnType<typeof vi.fn>
  let initCount = 0

  beforeEach(async () => {
    initCount = 0
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })

    fetchSpy = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      const method = body.method
      if (method === 'initialize') {
        initCount += 1
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-it-' + initCount,
            },
          },
        )
      }
      // notifications/initialized — no body needed
      return new Response('', { status: 202 })
    })
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('sends initialize then notifications/initialized in that order', async () => {
    const { ensureSession } = await import('../mcpClient')
    await ensureSession('http://srv', null)

    const calls = fetchSpy.mock.calls
    const methods = calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)).method)
    expect(methods).toEqual(['initialize', 'notifications/initialized'])
  })

  it('parses Mcp-Session-Id from response header and caches it', async () => {
    const { ensureSession } = await import('../mcpClient')
    const sid = await ensureSession('http://srv', null)
    expect(sid).toEqual('sess-it-1')

    const { useMcpStore } = await import('../mcpStore')
    expect(useMcpStore.getState().getSession('http://srv/mcp')?.sessionId).toEqual('sess-it-1')
  })

  it('returns null for stateless server (no Mcp-Session-Id header)', async () => {
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          { headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response('', { status: 202 })
    })

    const { ensureSession } = await import('../mcpClient')
    const sid = await ensureSession('http://srv', null)
    expect(sid).toBeNull()
  })

  it('dedupes concurrent calls into a single initialise', async () => {
    const { ensureSession } = await import('../mcpClient')
    const [a, b] = await Promise.all([
      ensureSession('http://srv', null),
      ensureSession('http://srv', null),
    ])
    expect(a).toEqual(b)
    expect(initCount).toEqual(1)
  })
})
