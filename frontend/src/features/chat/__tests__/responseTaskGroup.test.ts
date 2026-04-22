import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  getActiveGroup,
  clearActiveGroup,
  type GroupChild,
} from '../responseTaskGroup'

type MockChild = GroupChild & {
  onDelta: Mock; onStreamEnd: Mock; onCancel: Mock; teardown: Mock
  onPause?: Mock; onResume?: Mock
}

function makeChild(overrides: Partial<MockChild> = {}): MockChild {
  return {
    name: overrides.name ?? 'mock',
    onDelta: vi.fn(),
    onStreamEnd: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn(),
    teardown: vi.fn(),
    ...overrides,
  }
}

describe('ResponseTaskGroup', () => {
  const sendWs = vi.fn()
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }

  beforeEach(() => {
    sendWs.mockClear()
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('starts in before-first-delta state', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    expect(g.state).toBe('before-first-delta')
  })

  it('transitions to streaming on first onDelta', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hello')
    expect(g.state).toBe('streaming')
    expect(child.onDelta).toHaveBeenCalledWith('hello', 'c1')
  })

  it('transitions to tailing then done on onStreamEnd', async () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hi')
    g.onStreamEnd()
    await new Promise((r) => setTimeout(r, 0))
    expect(g.state).toBe('done')
    expect(child.onStreamEnd).toHaveBeenCalledWith('c1')
  })

  it('drains children sequentially on stream end', async () => {
    let resolveFirst: () => void = () => {
      throw new Error('first drain promise was not started')
    }
    const calls: string[] = []
    const first = makeChild({
      name: 'first',
      onStreamEnd: vi.fn(() => new Promise<void>((resolve) => {
        calls.push('first:start')
        resolveFirst = () => {
          calls.push('first:resolve')
          resolve()
        }
      })),
    })
    const second = makeChild({
      name: 'second',
      onStreamEnd: vi.fn(() => {
        calls.push('second:start')
        return Promise.resolve()
      }),
    })
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [first, second], sendWsMessage: sendWs, logger,
    })

    g.onDelta('hi')
    g.onStreamEnd()

    expect(calls).toEqual(['first:start'])
    expect(second.onStreamEnd).not.toHaveBeenCalled()

    resolveFirst()
    await new Promise((r) => setTimeout(r, 0))

    expect(calls).toEqual(['first:start', 'first:resolve', 'second:start'])
    expect(g.state).toBe('done')
  })

  it('cancel from before-first-delta sends chat.retract', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.cancel('barge-retract')
    expect(g.state).toBe('cancelled')
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.retract', correlation_id: 'c1', session_id: 's1',
    })
    expect(child.onCancel).toHaveBeenCalledWith('barge-retract', 'c1')
  })

  it('cancel from streaming sends chat.cancel', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hi')
    g.cancel('user-stop')
    expect(g.state).toBe('cancelled')
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.cancel', correlation_id: 'c1',
    })
  })

  it('cancel on terminal state is a no-op', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.cancel('user-stop')
    const callsBefore = sendWs.mock.calls.length
    g.cancel('user-stop')
    expect(sendWs.mock.calls.length).toBe(callsBefore)
  })

  it('pause/resume dispatch optional callbacks to children', () => {
    const onPause = vi.fn()
    const onResume = vi.fn()
    const child = makeChild({ onPause, onResume })
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hi')
    g.pause()
    expect(onPause).toHaveBeenCalled()
    g.resume()
    expect(onResume).toHaveBeenCalled()
  })

  it('pause is no-op outside streaming/tailing', () => {
    const onPause = vi.fn()
    const child = makeChild({ onPause })
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.pause()
    expect(onPause).not.toHaveBeenCalled()
  })
})

describe('ResponseTaskGroup registry', () => {
  const sendWs = vi.fn()
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }

  beforeEach(() => {
    sendWs.mockClear()
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('registerActiveGroup cancels the predecessor with reason superseded', () => {
    const child1 = { name: 'c', onDelta: vi.fn(), onStreamEnd: vi.fn(), onCancel: vi.fn(), teardown: vi.fn() }
    const g1 = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child1], sendWsMessage: sendWs, logger,
    })
    registerActiveGroup(g1)
    g1.onDelta('hi')

    const child2 = { name: 'c', onDelta: vi.fn(), onStreamEnd: vi.fn(), onCancel: vi.fn(), teardown: vi.fn() }
    const g2 = createResponseTaskGroup({
      correlationId: 'c2', sessionId: 's1', userId: 'u1',
      children: [child2], sendWsMessage: sendWs, logger,
    })
    registerActiveGroup(g2)

    expect(child1.onCancel).toHaveBeenCalledWith('superseded', 'c1')
    expect(g1.state).toBe('cancelled')
    expect(getActiveGroup()).toBe(g2)
  })

  it('terminal group auto-clears from registry', async () => {
    const child = { name: 'c', onDelta: vi.fn(), onStreamEnd: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), teardown: vi.fn() }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    registerActiveGroup(g)
    g.onDelta('hi')
    g.onStreamEnd()
    await new Promise((r) => setTimeout(r, 0))
    expect(getActiveGroup()).toBeNull()
  })
})
