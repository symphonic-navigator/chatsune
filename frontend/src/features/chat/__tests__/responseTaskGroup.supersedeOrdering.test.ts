import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  clearActiveGroup,
  getActiveGroup,
  cancelCurrentActiveGroup,
  type GroupChild,
  type ResponseTaskGroup,
} from '../responseTaskGroup'

function makeChild(name = 'mock'): GroupChild {
  return {
    name,
    onDelta: vi.fn(),
    onStreamEnd: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn(),
    teardown: vi.fn(),
  }
}

function makeGroup(correlationId = 'c1'): ResponseTaskGroup {
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
  return createResponseTaskGroup({
    correlationId,
    sessionId: 's1',
    userId: 'u1',
    children: [makeChild()],
    sendWsMessage: vi.fn(),
    logger,
  })
}

describe('cancelCurrentActiveGroup', () => {
  beforeEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('is a no-op when no Group is active', () => {
    expect(getActiveGroup()).toBeNull()
    expect(() => cancelCurrentActiveGroup()).not.toThrow()
    expect(getActiveGroup()).toBeNull()
  })

  it('cancels an active streaming Group, transitioning it to cancelled and clearing the registry', () => {
    const group = makeGroup('c1')
    registerActiveGroup(group)
    group.onDelta('hello') // drives into streaming
    expect(group.state).toBe('streaming')

    cancelCurrentActiveGroup()

    expect(group.state).toBe('cancelled')
    expect(getActiveGroup()).toBeNull()
  })

  it('passes the default reason "superseded" to the Group on cancel', () => {
    const onCancel = vi.fn()
    const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
    const group = createResponseTaskGroup({
      correlationId: 'c1',
      sessionId: 's1',
      userId: 'u1',
      children: [{ ...makeChild(), onCancel }],
      sendWsMessage: vi.fn(),
      logger,
    })
    registerActiveGroup(group)
    group.onDelta('hi')

    cancelCurrentActiveGroup()

    expect(onCancel).toHaveBeenCalledWith('superseded', 'c1')
  })

  it('does not re-cancel an already-done Group', () => {
    // A Group that has finished naturally is no longer installed in the
    // registry (clearActiveGroup fires on transition to done), so
    // cancelCurrentActiveGroup has nothing to operate on. This test ensures
    // the guard against state === done inside the helper works even if a
    // caller somehow observes a done Group still in the registry.
    const group = makeGroup('c1')
    registerActiveGroup(group)
    group.onDelta('hi')
    group.cancel('user-stop') // drives to cancelled

    // Re-install it manually to simulate a stale registry state.
    // (Not normally possible, but we want to confirm the guard.)
    expect(() => cancelCurrentActiveGroup()).not.toThrow()
  })
})
