import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BaseEvent } from '../../../core/types/events'

// Mock the connection module so we can assert on sendMessage.
const sendMessageMock = vi.fn()
vi.mock('../../../core/websocket/connection', () => ({
  sendMessage: (msg: unknown) => sendMessageMock(msg),
}))

// Mock runSandbox so the handler test doesn't spin up a real Worker.
const runSandboxMock = vi.fn()
vi.mock('../sandboxHost', () => ({
  runSandbox: (...args: unknown[]) => runSandboxMock(...args),
}))

// Mock the integrations registry / store so we can drive the
// integration-dispatch branch directly without registering real plugins.
const executeToolMock = vi.fn()
const getAllPluginsMock = vi.fn<() => Map<string, { executeTool: (...args: unknown[]) => Promise<string> }>>(
  () => new Map(),
)
vi.mock('../../integrations/registry', () => ({
  getAllPlugins: () => getAllPluginsMock(),
}))
vi.mock('../../integrations/store', () => ({
  useIntegrationsStore: {
    getState: () => ({
      getConfig: (_pluginId: string) => ({ effective_enabled: true, config: {} }),
    }),
  },
}))

// Use the real eventBus — it is a singleton module with no side effects
// and we want to exercise the actual subscription path.
import { eventBus } from '../../../core/websocket/eventBus'
import { useChatStore } from '../../../core/store/chatStore'
import { registerClientToolHandler } from '../clientToolHandler'

function makeEvent(payload: Record<string, unknown>): BaseEvent {
  return {
    id: 'evt-1',
    type: 'chat.client_tool.dispatch',
    sequence: '1-0',
    scope: 'user:u1',
    correlation_id: 'c1',
    timestamp: new Date().toISOString(),
    payload,
  }
}

describe('registerClientToolHandler', () => {
  let unregister: () => void

  beforeEach(() => {
    sendMessageMock.mockReset()
    runSandboxMock.mockReset()
    executeToolMock.mockReset()
    getAllPluginsMock.mockReset()
    getAllPluginsMock.mockReturnValue(new Map())
    eventBus.clear()
    // Reset the chat store's activeSessionId so each test starts clean.
    useChatStore.setState({ activeSessionId: null })
    unregister = registerClientToolHandler()
  })

  afterEach(() => {
    unregister()
    eventBus.clear()
    vi.useRealTimers()
  })

  it('runs calculate_js and sends the result back', async () => {
    runSandboxMock.mockResolvedValue({ stdout: '4', error: null })

    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-1',
      tool_name: 'calculate_js',
      arguments: { code: 'console.log(2+2)' },
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    // yield to pending microtasks (handler kicks off async work via void)
    await new Promise((r) => setTimeout(r, 0))
    await new Promise((r) => setTimeout(r, 0))

    expect(runSandboxMock).toHaveBeenCalledWith('console.log(2+2)', 5000, 4096)
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-1',
      result: { stdout: '4', error: null },
    })
  })

  it('sends an error result when tool_name is unknown', async () => {
    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-2',
      tool_name: 'python_exec',
      arguments: { code: 'print(1)' },
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    await new Promise((r) => setTimeout(r, 0))

    expect(runSandboxMock).not.toHaveBeenCalled()
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-2',
      result: { stdout: '', error: 'Unknown client tool: python_exec' },
    })
  })

  it('sends an error result when code is missing', async () => {
    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-3',
      tool_name: 'calculate_js',
      arguments: {},
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    await new Promise((r) => setTimeout(r, 0))

    expect(runSandboxMock).not.toHaveBeenCalled()
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-3',
      result: { stdout: '', error: 'No code provided' },
    })
  })

  it('sends client_tool_timeout when an integration tool exceeds timeout_ms', async () => {
    vi.useFakeTimers()
    // Plugin promise never resolves — simulates a hung integration tool.
    const neverResolving = new Promise<string>(() => { /* hangs forever */ })
    executeToolMock.mockReturnValue(neverResolving)
    getAllPluginsMock.mockReturnValue(
      new Map([['lovense', { executeTool: executeToolMock }]]),
    )

    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-timeout',
      tool_name: 'lovense_get_toys',
      arguments: {},
      timeout_ms: 1000,
      target_connection_id: 'conn-1',
    }))

    // Let the synchronous handler dispatch and reach the await.
    await Promise.resolve()
    await Promise.resolve()

    expect(sendMessageMock).not.toHaveBeenCalled()

    // Advance past the timeout and let the timer callback flush.
    await vi.advanceTimersByTimeAsync(1001)

    expect(sendMessageMock).toHaveBeenCalledTimes(1)
    const call = sendMessageMock.mock.calls[0][0] as {
      type: string
      tool_call_id: string
      result: { stdout: string; error: string | null }
    }
    expect(call.type).toBe('chat.client_tool.result')
    expect(call.tool_call_id).toBe('tc-timeout')
    expect(call.result.stdout).toBe('')
    expect(call.result.error).toContain('client_tool_timeout')
    expect(call.result.error).toContain('1000ms')
  })

  it('logs a warning when dispatch targets a non-active session but still executes', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => { /* swallow */ })
    runSandboxMock.mockResolvedValue({ stdout: '5', error: null })
    useChatStore.setState({ activeSessionId: 's-active' })

    eventBus.emit(makeEvent({
      session_id: 's-other',
      tool_call_id: 'tc-mismatch',
      tool_name: 'calculate_js',
      arguments: { code: 'console.log(5)' },
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    await new Promise((r) => setTimeout(r, 0))
    await new Promise((r) => setTimeout(r, 0))

    // Warning fired with session mismatch context.
    const warned = warnSpy.mock.calls.some((args) =>
      typeof args[0] === 'string' && args[0].includes('session mismatch'),
    )
    expect(warned).toBe(true)

    // Tool still executed and result was sent.
    expect(runSandboxMock).toHaveBeenCalled()
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-mismatch',
      result: { stdout: '5', error: null },
    })

    warnSpy.mockRestore()
  })
})
