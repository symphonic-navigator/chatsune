import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  clearGroupForSession,
  subscribeGroups,
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

function makeGroup(correlationId = 'c1', sessionId = 's1'): ResponseTaskGroup {
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
  return createResponseTaskGroup({
    correlationId,
    sessionId,
    userId: 'u1',
    children: [makeChild()],
    sendWsMessage: vi.fn(),
    logger,
  })
}

describe('subscribeGroups', () => {
  beforeEach(() => {
    clearGroupForSession('s1')
    clearGroupForSession('s2')
  })

  it('fires with the new (sessionId, group) on registerActiveGroup', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeGroups(listener)
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(listener).toHaveBeenCalledWith('s1', g)
    unsubscribe()
  })

  it('fires with (sessionId, null) on clearGroupForSession when a group was registered', () => {
    const g = makeGroup('c1')
    registerActiveGroup(g)
    const listener = vi.fn()
    const unsubscribe = subscribeGroups(listener)
    clearGroupForSession('s1')
    expect(listener).toHaveBeenCalledWith('s1', null)
    unsubscribe()
  })

  it('fires on state transitions (onDelta → streaming) carrying the same session id', () => {
    const g = makeGroup('c1')
    registerActiveGroup(g)
    const listener = vi.fn()
    const unsubscribe = subscribeGroups(listener)
    g.onDelta('hello')
    // onDelta drives before-first-delta → streaming, which is a transition.
    expect(listener).toHaveBeenCalledWith('s1', g)
    unsubscribe()
  })

  it('fires on cancel() transition with the (just-cancelled) group before it clears', () => {
    const g = makeGroup('c1')
    registerActiveGroup(g)
    g.onDelta('hi')
    const seen: Array<readonly [string, ResponseTaskGroup | null]> = []
    const unsubscribe = subscribeGroups((sid, group) => {
      seen.push([sid, group])
    })
    g.cancel('user-stop')
    // Expect at least one notification from the cancel transition and one
    // from clearGroupForSession inside the transition, in that order.
    expect(seen.length).toBeGreaterThanOrEqual(1)
    expect(seen[seen.length - 1][0]).toBe('s1')
    expect(seen[seen.length - 1][1]).toBeNull()
    unsubscribe()
  })

  it('unsubscribe stops further notifications', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeGroups(listener)
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
    const unsub1 = subscribeGroups(thrower)
    const unsub2 = subscribeGroups(other)
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(thrower).toHaveBeenCalled()
    expect(other).toHaveBeenCalledWith('s1', g)
    unsub1()
    unsub2()
  })

  it('a listener that unsubscribes itself during callback does not break iteration', () => {
    const after = vi.fn()
    let unsubSelf: (() => void) | null = null
    const selfUnsubbing = vi.fn(() => {
      unsubSelf?.()
    })
    unsubSelf = subscribeGroups(selfUnsubbing)
    const unsubAfter = subscribeGroups(after)
    const g = makeGroup('c1')
    registerActiveGroup(g)
    expect(selfUnsubbing).toHaveBeenCalledTimes(1)
    expect(after).toHaveBeenCalledWith('s1', g)
    // Second notification should only reach `after`, not the self-unsubbed one.
    const g2 = makeGroup('c2')
    registerActiveGroup(g2)
    expect(selfUnsubbing).toHaveBeenCalledTimes(1)
    expect(after).toHaveBeenLastCalledWith('s1', g2)
    unsubAfter()
  })

  it('listener fires for distinct session ids independently', () => {
    const seen: Array<readonly [string, ResponseTaskGroup | null]> = []
    const unsubscribe = subscribeGroups((sid, group) => {
      seen.push([sid, group])
    })
    const ga = makeGroup('cA', 's1')
    const gb = makeGroup('cB', 's2')
    registerActiveGroup(ga)
    registerActiveGroup(gb)
    const sids = seen.map(([sid]) => sid)
    expect(sids).toContain('s1')
    expect(sids).toContain('s2')
    unsubscribe()
  })
})
