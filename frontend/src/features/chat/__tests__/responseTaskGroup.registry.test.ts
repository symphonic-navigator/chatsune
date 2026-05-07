import { describe, it, expect, vi } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  getActiveGroupForSession,
  cancelGroupForSession,
  clearGroupForSession,
  subscribeGroups,
} from '../responseTaskGroup'

const noopLogger = {
  info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn(),
}

function makeGroup(sessionId: string, correlationId: string) {
  return createResponseTaskGroup({
    correlationId,
    sessionId,
    userId: 'user-test',
    children: [],
    sendWsMessage: vi.fn(),
    logger: noopLogger,
  })
}

describe('responseTaskGroup multi-group registry', () => {
  it('registers groups under their session id and looks them up by session', () => {
    const a = makeGroup('session-A', 'cor-A')
    const b = makeGroup('session-B', 'cor-B')
    registerActiveGroup(a)
    registerActiveGroup(b)

    expect(getActiveGroupForSession('session-A')).toBe(a)
    expect(getActiveGroupForSession('session-B')).toBe(b)
    clearGroupForSession('session-A')
    clearGroupForSession('session-B')
  })

  it('registering a second group for the same session supersedes the first', () => {
    const a = makeGroup('session-A', 'cor-A1')
    const b = makeGroup('session-A', 'cor-A2')
    registerActiveGroup(a)
    registerActiveGroup(b)

    expect(getActiveGroupForSession('session-A')).toBe(b)
    expect(a.state).toBe('cancelled')
    clearGroupForSession('session-A')
  })

  it('cancelGroupForSession only affects the named session', () => {
    const a = makeGroup('session-A', 'cor-A')
    const b = makeGroup('session-B', 'cor-B')
    registerActiveGroup(a)
    registerActiveGroup(b)

    cancelGroupForSession('session-A', 'teardown')

    expect(a.state).toBe('cancelled')
    expect(b.state).toBe('before-first-delta')
    clearGroupForSession('session-B')
  })

  it('same-session supersede emits no null pulse to subscribers', () => {
    const seen: Array<string | null> = []
    const unsubscribe = subscribeGroups((sid, group) => {
      if (sid !== 'session-A') return
      if (group === null) {
        seen.push(null)
      } else {
        seen.push(group.id)
      }
    })

    const a = makeGroup('session-A', 'cor-A1')
    registerActiveGroup(a)
    const b = makeGroup('session-A', 'cor-A2')
    registerActiveGroup(b)

    unsubscribe()
    clearGroupForSession('session-A')

    // The valid sequence is: cor-A1 (initial register), cor-A1 (cancelled
    // notify on supersede), cor-A2 (new register). NO null notify between
    // the cancellation and the new registration.
    const indexOfNullBetween = seen.findIndex((entry, i) => entry === null && i < seen.length - 1)
    expect(indexOfNullBetween).toBe(-1)
  })
})
