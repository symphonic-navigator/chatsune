import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  createResponseTaskGroup,
  getActiveGroup,
  clearActiveGroup,
  type CancelReason,
} from '../responseTaskGroup'

/**
 * Per-reason verification of which WS frame the Group emits on cancel.
 *
 * The matrix below is the canonical contract the backend relies on:
 * `chat.retract` retracts the user message, `chat.cancel` stops generation
 * but leaves transcript intact, no frame at all means "let the backend
 * keep streaming and persist on its own" (used during teardown so a
 * navigation-away does not destroy the user's message).
 */

function makeLogger() {
  return { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
}

describe('ResponseTaskGroup cancel reasons → WS frame', () => {
  beforeEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('teardown before first delta sends nothing', () => {
    const sendWs = vi.fn()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger: makeLogger(),
    })
    g.cancel('teardown')
    expect(g.state).toBe('cancelled')
    expect(sendWs).not.toHaveBeenCalled()
  })

  it('teardown after first delta sends nothing', () => {
    const sendWs = vi.fn()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger: makeLogger(),
    })
    g.onDelta('hello')
    g.cancel('teardown')
    expect(g.state).toBe('cancelled')
    expect(sendWs).not.toHaveBeenCalled()
  })

  it('barge-retract before first delta sends chat.retract with session_id', () => {
    const sendWs = vi.fn()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger: makeLogger(),
    })
    g.cancel('barge-retract')
    expect(sendWs).toHaveBeenCalledTimes(1)
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.retract', correlation_id: 'c1', session_id: 's1',
    })
  })

  it('barge-retract after first delta downgrades to chat.cancel', () => {
    const sendWs = vi.fn()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger: makeLogger(),
    })
    g.onDelta('partial output')
    g.cancel('barge-retract')
    expect(sendWs).toHaveBeenCalledTimes(1)
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.cancel', correlation_id: 'c1',
    })
  })

  it.each<CancelReason>(['barge-cancel', 'user-stop', 'superseded'])(
    '%s before first delta sends chat.cancel',
    (reason) => {
      const sendWs = vi.fn()
      const g = createResponseTaskGroup({
        correlationId: 'c1', sessionId: 's1', userId: 'u1',
        children: [], sendWsMessage: sendWs, logger: makeLogger(),
      })
      g.cancel(reason)
      expect(sendWs).toHaveBeenCalledTimes(1)
      expect(sendWs).toHaveBeenCalledWith({
        type: 'chat.cancel', correlation_id: 'c1',
      })
    },
  )

  it.each<CancelReason>(['barge-cancel', 'user-stop', 'superseded'])(
    '%s after first delta sends chat.cancel',
    (reason) => {
      const sendWs = vi.fn()
      const g = createResponseTaskGroup({
        correlationId: 'c1', sessionId: 's1', userId: 'u1',
        children: [], sendWsMessage: sendWs, logger: makeLogger(),
      })
      g.onDelta('partial')
      g.cancel(reason)
      expect(sendWs).toHaveBeenCalledTimes(1)
      expect(sendWs).toHaveBeenCalledWith({
        type: 'chat.cancel', correlation_id: 'c1',
      })
    },
  )

  it('teardown still drives child onCancel and teardown', async () => {
    const sendWs = vi.fn()
    const onCancel = vi.fn()
    const teardown = vi.fn().mockResolvedValue(undefined)
    const child = {
      name: 'mock',
      onDelta: vi.fn(),
      onStreamEnd: vi.fn(),
      onCancel,
      teardown,
    }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger: makeLogger(),
    })
    g.cancel('teardown')
    expect(onCancel).toHaveBeenCalledWith('teardown', 'c1')
    // teardown is dispatched asynchronously via Promise.allSettled
    await new Promise((r) => setTimeout(r, 0))
    expect(teardown).toHaveBeenCalled()
    expect(sendWs).not.toHaveBeenCalled()
  })
})
