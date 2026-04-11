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

// Use the real eventBus — it is a singleton module with no side effects
// and we want to exercise the actual subscription path.
import { eventBus } from '../../../core/websocket/eventBus'
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
    eventBus.clear()
    unregister = registerClientToolHandler()
  })

  afterEach(() => {
    unregister()
    eventBus.clear()
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
})
