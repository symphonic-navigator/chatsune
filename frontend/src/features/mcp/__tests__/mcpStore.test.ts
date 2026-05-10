import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useMcpStore } from '../mcpStore'
import type { McpGatewayConfig, McpSessionGateway } from '../types'

const sendMessageMock = vi.fn()
vi.mock('../../../core/websocket/connection', () => ({
  sendMessage: (...args: unknown[]) => sendMessageMock(...args),
}))

const syncLocalGatewayToBackendMock = vi.fn<(gw: McpGatewayConfig) => Promise<McpSessionGateway | null>>()
vi.mock('../useMcpEvents', () => ({
  syncLocalGatewayToBackend: (gw: McpGatewayConfig) => syncLocalGatewayToBackendMock(gw),
}))

function makeGateway(overrides: Partial<McpGatewayConfig> = {}): McpGatewayConfig {
  return {
    id: 'gw-test',
    name: 'Test Gateway',
    url: 'http://localhost:9999',
    api_key: null,
    enabled: true,
    disabled_tools: [],
    server_configs: {},
    tool_overrides: [],
    ...overrides,
  }
}

function makeSessionEntry(namespace: string): McpSessionGateway {
  return {
    namespace,
    tier: 'local' as const,
    tools: [
      { name: `${namespace}__do_thing`, description: '', server_name: 'srv' },
    ],
    collisions: [],
  }
}

describe('mcpStore mutators sync sessionGateways and notify backend', () => {
  beforeEach(() => {
    sendMessageMock.mockReset()
    syncLocalGatewayToBackendMock.mockReset()
    localStorage.clear()
    useMcpStore.setState({ localGateways: [], sessionGateways: [] })
  })

  afterEach(() => {
    useMcpStore.setState({ localGateways: [], sessionGateways: [] })
  })

  it('addLocalGateway: discovers, sends mcp.tools.register, appends to sessionGateways', async () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    syncLocalGatewayToBackendMock.mockResolvedValueOnce(makeSessionEntry('one'))

    await useMcpStore.getState().addLocalGateway(gw)

    expect(syncLocalGatewayToBackendMock).toHaveBeenCalledWith(gw)
    const session = useMcpStore.getState().sessionGateways
    expect(session).toHaveLength(1)
    expect(session[0]?.namespace).toBe('one')
  })

  it('addLocalGateway: gracefully handles unreachable gateway (no sessionGateways change)', async () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    syncLocalGatewayToBackendMock.mockResolvedValueOnce(null)

    await useMcpStore.getState().addLocalGateway(gw)

    expect(useMcpStore.getState().sessionGateways).toHaveLength(0)
  })

  it('deleteLocalGateway: sends mcp.tools.deregister and removes from sessionGateways', () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    useMcpStore.setState({
      localGateways: [gw],
      sessionGateways: [makeSessionEntry('one')],
    })

    useMcpStore.getState().deleteLocalGateway('gw-1')

    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: 'gw-1' },
    })
    expect(useMcpStore.getState().sessionGateways).toHaveLength(0)
    expect(useMcpStore.getState().localGateways).toHaveLength(0)
  })

  it('deleteLocalGateway: unknown id is a no-op (no message, no state change)', () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    useMcpStore.setState({
      localGateways: [gw],
      sessionGateways: [makeSessionEntry('one')],
    })

    useMcpStore.getState().deleteLocalGateway('does-not-exist')

    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(useMcpStore.getState().sessionGateways).toHaveLength(1)
    expect(useMcpStore.getState().localGateways).toHaveLength(1)
  })

  it('updateLocalGateway: deregisters then re-registers and replaces session entry', async () => {
    const gw = makeGateway({ id: 'gw-1', name: 'old' })
    useMcpStore.setState({
      localGateways: [gw],
      sessionGateways: [makeSessionEntry('old')],
    })
    syncLocalGatewayToBackendMock.mockResolvedValueOnce(makeSessionEntry('new'))

    await useMcpStore.getState().updateLocalGateway('gw-1', { name: 'new', url: 'http://different' })

    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: 'gw-1' },
    })
    expect(syncLocalGatewayToBackendMock).toHaveBeenCalledOnce()
    const session = useMcpStore.getState().sessionGateways
    expect(session).toHaveLength(1)
    expect(session[0]?.namespace).toBe('new')
  })
})

describe('mcpStore — session slice', () => {
  beforeEach(() => {
    // Reset the sessions slice between tests
    useMcpStore.setState({ sessions: {} })
  })

  it('setSession stores the session id keyed by URL', () => {
    useMcpStore.getState().setSession('http://srv/mcp', 'sess-1')
    expect(useMcpStore.getState().getSession('http://srv/mcp')).toEqual({
      sessionId: 'sess-1',
      initialising: null,
    })
  })

  it('setSession can mark a server as stateless with null', () => {
    useMcpStore.getState().setSession('http://srv/mcp', null)
    expect(useMcpStore.getState().getSession('http://srv/mcp')?.sessionId).toBeNull()
  })

  it('clearSession removes the entry', () => {
    useMcpStore.getState().setSession('http://srv/mcp', 'sess-1')
    useMcpStore.getState().clearSession('http://srv/mcp')
    expect(useMcpStore.getState().getSession('http://srv/mcp')).toBeUndefined()
  })

  it('setSession overwrites an existing entry (URL edit scenario)', () => {
    useMcpStore.getState().setSession('http://srv/mcp', 'old')
    useMcpStore.getState().setSession('http://srv/mcp', 'new')
    expect(useMcpStore.getState().getSession('http://srv/mcp')?.sessionId).toEqual('new')
  })
})
