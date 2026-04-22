import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import {
  registerActiveGroup,
  getActiveGroup,
  clearActiveGroup,
  createResponseTaskGroup,
  type ResponseTaskGroup,
  type GroupChild,
} from '../../chat/responseTaskGroup'
import { createBargeController, type BargeControllerDeps } from '../bargeController'

function makeChild(overrides: Partial<GroupChild> = {}): GroupChild & {
  onDelta: Mock; onStreamEnd: Mock; onCancel: Mock; teardown: Mock
  onPause?: Mock; onResume?: Mock
} {
  return {
    name: overrides.name ?? 'mock',
    onDelta: vi.fn(),
    onStreamEnd: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn(),
    teardown: vi.fn(),
    ...overrides,
  } as any
}

function makeGroup(correlationId: string, extraChildOverrides: Partial<GroupChild> = {}): {
  group: ResponseTaskGroup
  child: ReturnType<typeof makeChild>
  sendWs: Mock
} {
  const sendWs = vi.fn()
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
  const child = makeChild({
    onPause: vi.fn(),
    onResume: vi.fn(),
    ...extraChildOverrides,
  })
  const group = createResponseTaskGroup({
    correlationId,
    sessionId: 's1',
    userId: 'u1',
    children: [child],
    sendWsMessage: sendWs,
    logger,
  })
  return { group, child, sendWs }
}

function makeLogger() {
  return { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
}

function makeDeps(overrides: Partial<BargeControllerDeps> = {}): BargeControllerDeps & {
  buildAndRegisterGroup: Mock
  sendChatMessage: Mock
} {
  return {
    buildAndRegisterGroup: vi.fn((correlationId: string, _transcript: string) => {
      // Default: build a fresh Group and register it.
      const { group } = makeGroup(correlationId)
      registerActiveGroup(group)
      return group.id
    }),
    sendChatMessage: vi.fn(),
    logger: makeLogger(),
    ...overrides,
  } as any
}

describe('bargeController', () => {
  beforeEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  describe('start()', () => {
    it('creates a Barge with pausedGroupId=null and does not throw when no active Group', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)

      const barge = ctrl.start()

      expect(barge.pausedGroupId).toBeNull()
      expect(barge.state).toBe('pending-stt')
      expect(typeof barge.id).toBe('string')
      expect(barge.id.length).toBeGreaterThan(0)
      expect(ctrl.current).toBe(barge)
      expect(deps.buildAndRegisterGroup).not.toHaveBeenCalled()
      expect(deps.sendChatMessage).not.toHaveBeenCalled()
    })

    it('captures pausedGroupId from active Group and calls Group.pause()', () => {
      const { group, child } = makeGroup('g1')
      registerActiveGroup(group)
      group.onDelta('hello')   // put group into streaming so pause() is not a no-op

      const ctrl = createBargeController(makeDeps())
      const barge = ctrl.start()

      expect(barge.pausedGroupId).toBe('g1')
      expect(barge.state).toBe('pending-stt')
      expect((child as any).onPause).toHaveBeenCalledTimes(1)
      expect(ctrl.current).toBe(barge)
    })
  })

  describe('commit()', () => {
    it('on valid pending Barge: builds+registers new Group, then sends chat.send, clears current', () => {
      const { group } = makeGroup('g-old')
      registerActiveGroup(group)
      group.onDelta('streaming')

      const callOrder: string[] = []
      const deps = makeDeps({
        buildAndRegisterGroup: vi.fn((correlationId: string, _transcript: string) => {
          callOrder.push('buildAndRegisterGroup')
          const { group: newGroup } = makeGroup(correlationId)
          registerActiveGroup(newGroup)
          return newGroup.id
        }),
        sendChatMessage: vi.fn(() => { callOrder.push('sendChatMessage') }),
      })
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()

      ctrl.commit(barge, 'hello world')

      expect(deps.buildAndRegisterGroup).toHaveBeenCalledTimes(1)
      expect(deps.sendChatMessage).toHaveBeenCalledTimes(1)
      // Same correlationId passed to both, and it is a UUID-ish string.
      const corrIdArg = (deps.buildAndRegisterGroup as Mock).mock.calls[0][0]
      const transcriptArg = (deps.buildAndRegisterGroup as Mock).mock.calls[0][1]
      expect(typeof corrIdArg).toBe('string')
      expect(corrIdArg.length).toBeGreaterThan(0)
      expect(transcriptArg).toBe('hello world')
      expect((deps.sendChatMessage as Mock).mock.calls[0][0]).toBe(corrIdArg)
      expect((deps.sendChatMessage as Mock).mock.calls[0][1]).toBe('hello world')
      // Ordering: buildAndRegisterGroup before sendChatMessage.
      expect(callOrder).toEqual(['buildAndRegisterGroup', 'sendChatMessage'])
      expect(ctrl.current).toBeNull()
    })

    it('silently no-ops on already-stale Barge', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()
      ctrl.stale(barge)

      ctrl.commit(barge, 'late transcript')

      expect(deps.buildAndRegisterGroup).not.toHaveBeenCalled()
      expect(deps.sendChatMessage).not.toHaveBeenCalled()
    })

    it('silently no-ops on non-current Barge (superseded by another start())', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const b1 = ctrl.start()
      const b2 = ctrl.start()

      ctrl.commit(b1, 'stale transcript')

      expect(deps.buildAndRegisterGroup).not.toHaveBeenCalled()
      expect(deps.sendChatMessage).not.toHaveBeenCalled()
      expect(ctrl.current).toBe(b2)
    })
  })

  describe('resume()', () => {
    it('with pausedGroupId matching activeGroup: calls activeGroup.resume(), marks resumed, clears current', () => {
      const { group, child } = makeGroup('g1')
      registerActiveGroup(group)
      group.onDelta('streaming')

      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()
      ;(child as any).onResume.mockClear()

      ctrl.resume(barge)

      expect((child as any).onResume).toHaveBeenCalledTimes(1)
      expect(barge.state).toBe('resumed')
      expect(ctrl.current).toBeNull()
    })

    it('with pausedGroupId not matching activeGroup: does not call resume() but still transitions', () => {
      const { group: g1 } = makeGroup('g1')
      registerActiveGroup(g1)
      g1.onDelta('streaming')

      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()

      // Swap in a new active Group while STT is in flight.
      const { group: g2, child: child2 } = makeGroup('g2')
      registerActiveGroup(g2)
      g2.onDelta('streaming')
      ;(child2 as any).onResume.mockClear()

      ctrl.resume(barge)

      expect((child2 as any).onResume).not.toHaveBeenCalled()
      expect(barge.state).toBe('resumed')
      expect(ctrl.current).toBeNull()
    })

    it('with pausedGroupId=null: no resume call (nothing was paused)', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()  // no active group, so pausedGroupId=null

      // Install a Group now (unrelated to this barge).
      const { group, child } = makeGroup('g1')
      registerActiveGroup(group)
      group.onDelta('streaming')
      ;(child as any).onResume.mockClear()

      ctrl.resume(barge)

      expect((child as any).onResume).not.toHaveBeenCalled()
      expect(barge.state).toBe('resumed')
      expect(ctrl.current).toBeNull()
    })
  })

  describe('stale()', () => {
    it('with matching paused Group: un-pauses (mirrors handleMisfire) and marks stale', () => {
      const { group, child } = makeGroup('g1')
      registerActiveGroup(group)
      group.onDelta('streaming')

      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()
      ;(child as any).onResume.mockClear()

      ctrl.stale(barge)

      expect((child as any).onResume).toHaveBeenCalledTimes(1)
      expect(barge.state).toBe('stale')
      expect(ctrl.current).toBeNull()
    })

    it('with no matching paused Group: marks stale, no side-effect', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()  // no active group

      ctrl.stale(barge)

      expect(barge.state).toBe('stale')
      expect(ctrl.current).toBeNull()
    })
  })

  describe('abandonAll()', () => {
    it('with pending barge + active group: cancels with reason=teardown, marks abandoned, clears current', () => {
      const { group, child, sendWs } = makeGroup('g1')
      registerActiveGroup(group)
      group.onDelta('streaming')

      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const barge = ctrl.start()

      ctrl.abandonAll()

      expect(barge.state).toBe('abandoned')
      expect(ctrl.current).toBeNull()
      expect(group.state).toBe('cancelled')
      expect((child as any).onCancel).toHaveBeenCalledWith('teardown', 'g1')
      expect(sendWs).toHaveBeenCalledWith({ type: 'chat.cancel', correlation_id: 'g1' })
    })

    it('with no current barge and no active group: no-op, does not throw', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)

      expect(() => ctrl.abandonAll()).not.toThrow()
      expect(ctrl.current).toBeNull()
    })
  })

  describe('rapid re-start()', () => {
    it('first Barge becomes non-current; commit(oldBarge,...) is a no-op', () => {
      const deps = makeDeps()
      const ctrl = createBargeController(deps)
      const b1 = ctrl.start()
      const b2 = ctrl.start()

      expect(b1).not.toBe(b2)
      expect(ctrl.current).toBe(b2)
      expect(b1 !== ctrl.current).toBe(true)

      ctrl.commit(b1, 'from stale barge')

      expect(deps.buildAndRegisterGroup).not.toHaveBeenCalled()
      expect(deps.sendChatMessage).not.toHaveBeenCalled()
      // b2 is still the current Barge.
      expect(ctrl.current).toBe(b2)
    })
  })
})
