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
