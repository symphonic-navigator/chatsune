import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhase } from '../usePhase'
import { useConversationModeStore } from '../stores/conversationModeStore'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  getActiveGroup,
  clearActiveGroup,
  type GroupChild,
} from '../../chat/responseTaskGroup'

function silentLogger() {
  return { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
}

function mockChild(): GroupChild {
  return {
    name: 'mock',
    onDelta: vi.fn(),
    onStreamEnd: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn(),
    teardown: vi.fn(),
  }
}

function resetStore() {
  useConversationModeStore.setState({
    active: false,
    phase: 'idle',
    isHolding: false,
    previousReasoningOverride: null,
    currentBargeState: null,
    sttInFlight: false,
    vadActive: false,
  })
}

describe('usePhase', () => {
  beforeEach(() => {
    resetStore()
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  afterEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
    resetStore()
  })

  it('re-renders when a store field changes (isHolding → held)', () => {
    useConversationModeStore.getState().enter()
    const { result } = renderHook(() => usePhase())

    expect(result.current).toBe('listening')

    act(() => {
      useConversationModeStore.getState().setHolding(true)
    })

    expect(result.current).toBe('held')
  })

  it('re-renders when the active Group transitions (streaming → speaking → listening on cancel)', () => {
    useConversationModeStore.getState().enter()
    const group = createResponseTaskGroup({
      correlationId: 'corr-usephase-1',
      sessionId: 'sess-1',
      userId: 'user-1',
      children: [mockChild()],
      sendWsMessage: vi.fn(),
      logger: silentLogger(),
    })

    const { result } = renderHook(() => usePhase())

    // Initially no active Group → listening.
    expect(result.current).toBe('listening')

    // Register + push into streaming via a delta. Both state transitions
    // fire a notifyActiveGroup, which should flow through useSyncExternalStore.
    act(() => {
      registerActiveGroup(group)
    })
    expect(result.current).toBe('thinking')

    act(() => {
      group.onDelta('hello')
    })
    expect(result.current).toBe('speaking')

    act(() => {
      group.cancel('teardown')
    })
    expect(result.current).toBe('listening')
  })
})
