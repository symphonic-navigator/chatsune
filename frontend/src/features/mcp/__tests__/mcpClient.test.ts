import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mcpToolsList, mcpToolsCall } from '../mcpClient'

describe('mcpClient — Streamable HTTP Accept header', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(async () => {
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })
    fetchSpy = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-accept',
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/list or tools/call
      return new Response(
        JSON.stringify({ jsonrpc: '2.0', id: body.id, result: { tools: [], content: [] } }),
        { headers: { 'content-type': 'application/json' } },
      )
    })
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('mcpToolsList sends Accept: application/json, text/event-stream', async () => {
    await mcpToolsList('http://example.com', null)
    const listCall = fetchSpy.mock.calls.find(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).method === 'tools/list',
    )!
    expect(listCall).toBeDefined()
    const init = listCall[1] as RequestInit
    const accept = (init.headers as Record<string, string>)['Accept'] ?? ''
    expect(accept).toContain('application/json')
    expect(accept).toContain('text/event-stream')
  })

  it('mcpToolsCall sends Accept: application/json, text/event-stream', async () => {
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-accept-test',
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/call
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { content: [{ type: 'text', text: 'ok' }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })
    await mcpToolsCall('http://example.com', null, 'ping', {})
    const toolsCallIndex = fetchSpy.mock.calls.findIndex(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).method === 'tools/call',
    )
    expect(toolsCallIndex).toBeGreaterThanOrEqual(0)
    const init = fetchSpy.mock.calls[toolsCallIndex][1] as RequestInit
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

describe('mcpToolsList lifecycle', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(async () => {
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })
    fetchSpy = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-list',
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/list
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { tools: [{ name: 't1', description: '', inputSchema: {} }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('runs initialise then sends Mcp-Session-Id on tools/list', async () => {
    const { mcpToolsList } = await import('../mcpClient')
    const out = await mcpToolsList('http://srv', null)
    expect(out.tools.length).toEqual(1)

    const listCall = fetchSpy.mock.calls.find(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).method === 'tools/list',
    )!
    const headers = (listCall[1] as RequestInit).headers as Record<string, string>
    expect(headers['Mcp-Session-Id']).toEqual('sess-list')
  })
})

describe('mcpToolsCall lifecycle', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(async () => {
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })
    fetchSpy = vi.fn()
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('sends Mcp-Session-Id on tool call after initialise', async () => {
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-tc',
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/call
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { content: [{ type: 'text', text: 'ok' }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })

    const { mcpToolsCall } = await import('../mcpClient')
    const out = await mcpToolsCall('http://srv', null, 't', {})
    expect(out.error).toBeNull()
    expect(out.stdout).toEqual('ok')

    const callRequest = fetchSpy.mock.calls.find(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).method === 'tools/call',
    )!
    const headers = (callRequest[1] as RequestInit).headers as Record<string, string>
    expect(headers['Mcp-Session-Id']).toEqual('sess-tc')
  })

  it('on 404 clears session, re-initialises, retries once', async () => {
    let initCount = 0
    let callCount = 0
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        initCount += 1
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-' + initCount,
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/call
      callCount += 1
      const headers = init.headers as Record<string, string>
      if (headers['Mcp-Session-Id'] === 'sess-1' && callCount === 1) {
        return new Response('', { status: 404 })
      }
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { content: [{ type: 'text', text: 'recovered' }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })

    const { mcpToolsCall } = await import('../mcpClient')
    const out = await mcpToolsCall('http://srv', null, 't', {})
    expect(out.error).toBeNull()
    expect(out.stdout).toEqual('recovered')
    expect(initCount).toEqual(2)
    expect(callCount).toEqual(2)
  })

  it('does not retry when there is no session id (stateless server)', async () => {
    let callCount = 0
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          { headers: { 'content-type': 'application/json' } }, // no mcp-session-id
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      callCount += 1
      return new Response('', { status: 404 })
    })

    const { mcpToolsCall } = await import('../mcpClient')
    const out = await mcpToolsCall('http://srv', null, 't', {})
    expect(out.error).toBeTruthy()
    expect(callCount).toEqual(1)  // no retry
  })
})
