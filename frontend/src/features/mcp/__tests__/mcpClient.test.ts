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
