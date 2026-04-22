import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  clearActiveGroup,
  getActiveGroup,
  subscribeActiveGroup,
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

describe('subscribeActiveGroup', () => {
  beforeEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('fires with the new group on registerActiveGroup', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeActiveGroup(listener)
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(listener).toHaveBeenCalledWith(g)
    unsubscribe()
  })

  it('fires with null on clearActiveGroup when the cleared group was active', () => {
    const g = makeGroup('c1')
    registerActiveGroup(g)
    const listener = vi.fn()
    const unsubscribe = subscribeActiveGroup(listener)
    clearActiveGroup(g)
    expect(listener).toHaveBeenCalledWith(null)
    unsubscribe()
  })

  it('fires on state transitions (onDelta → streaming)', () => {
    const g = makeGroup('c1')
    registerActiveGroup(g)
    const listener = vi.fn()
    const unsubscribe = subscribeActiveGroup(listener)
    g.onDelta('hello')
    // onDelta drives before-first-delta → streaming, which is a transition.
    expect(listener).toHaveBeenCalledWith(g)
    unsubscribe()
  })

  it('fires on cancel() transition with the (just-cancelled) group before it clears', () => {
    const g = makeGroup('c1')
    registerActiveGroup(g)
    g.onDelta('hi')
    const seen: Array<ResponseTaskGroup | null> = []
    const unsubscribe = subscribeActiveGroup((group) => {
      seen.push(group)
    })
    g.cancel('user-stop')
    // Expect at least one notification from the cancel transition and one
    // from clearActiveGroup inside the transition, in that order.
    expect(seen.length).toBeGreaterThanOrEqual(1)
    expect(seen[seen.length - 1]).toBeNull()
    unsubscribe()
  })

  it('unsubscribe stops further notifications', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeActiveGroup(listener)
    unsubscribe()
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(listener).not.toHaveBeenCalled()
  })

  it('a throwing listener does not prevent other listeners from being called', () => {
    const thrower = vi.fn(() => {
      throw new Error('boom')
    })
    const other = vi.fn()
    const unsub1 = subscribeActiveGroup(thrower)
    const unsub2 = subscribeActiveGroup(other)
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(thrower).toHaveBeenCalled()
    expect(other).toHaveBeenCalledWith(g)
    unsub1()
    unsub2()
  })

  it('a listener that unsubscribes itself during callback does not break iteration', () => {
    const after = vi.fn()
    let unsubSelf: (() => void) | null = null
    const selfUnsubbing = vi.fn(() => {
      unsubSelf?.()
    })
    unsubSelf = subscribeActiveGroup(selfUnsubbing)
    const unsubAfter = subscribeActiveGroup(after)
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(selfUnsubbing).toHaveBeenCalledTimes(1)
    expect(after).toHaveBeenCalledWith(g)
    // Second notification should only reach `after`, not the self-unsubbed one.
    const g2 = makeGroup('c2')
    registerActiveGroup(g2)
    expect(selfUnsubbing).toHaveBeenCalledTimes(1)
    expect(after).toHaveBeenLastCalledWith(g2)
    unsubAfter()
  })
})
