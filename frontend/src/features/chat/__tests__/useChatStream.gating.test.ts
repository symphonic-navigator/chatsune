import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore, type SessionStreamingState } from '../../../core/store/chatStore'
import { handleChatEvent } from '../useChatStream'
import type { BaseEvent } from '../../../core/types/events'

// Mock the notification store and compaction toasts so we can spy on
// addNotification / showCompactionSuccess without importing the real
// stores which may have side-effects.
const mockAddNotification = vi.fn()
vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: {
    getState: () => ({ addNotification: mockAddNotification }),
  },
}))

const mockShowCompactionSuccess = vi.fn()
const mockShowCompactionFailure = vi.fn()
vi.mock('../compaction/toasts', () => ({
  showCompactionSuccess: (...args: unknown[]) => mockShowCompactionSuccess(...args),
  showCompactionFailure: (...args: unknown[]) => mockShowCompactionFailure(...args),
}))

// Mock the active-group registry. The CHAT_CONTENT_DELTA handler still
// asks for it after the slot gate to dispatch ``onDelta``; we feed it a
// minimal stub that records calls so the gating-only test does not need
// to assemble a real ResponseTaskGroup.
let mockActiveGroup: { id: string; onDelta: (delta: string) => void } | null = null
vi.mock('../responseTaskGroup', () => ({
  getActiveGroupForSession: () => mockActiveGroup,
  subscribeGroups: () => () => {},
}))

const mockSendMessage = vi.fn()
const SESSION_ID = 's1'

function makeEvent(overrides: Partial<BaseEvent> & { type: string }): BaseEvent {
  return {
    id: 'evt-1',
    type: overrides.type,
    sequence: 1,
    scope: 'session:s1',
    correlation_id: overrides.correlation_id ?? 'c1',
    timestamp: new Date().toISOString(),
    payload: overrides.payload ?? {},
  } as unknown as BaseEvent
}

type StoreState = ReturnType<typeof useChatStore.getState>

function seedStream(patch: Partial<SessionStreamingState>): void {
  const empty: SessionStreamingState = {
    isWaitingForResponse: false,
    isStreaming: false,
    correlationId: null,
    streamingContent: '',
    streamingThinking: '',
    streamingEvents: [],
    streamingRefusalText: null,
    streamingToolCalls: new Map(),
    visionDescriptions: {},
    streamingSlow: false,
  }
  const next = new Map<string, SessionStreamingState>()
  next.set(SESSION_ID, { ...empty, ...patch })
  useChatStore.setState({
    streamsBySession: next,
    activeSessionId: SESSION_ID,
  } as Partial<StoreState> as StoreState)
}

describe('useChatStream — CHAT_CONTENT_DELTA slot-based gating (Fix 18)', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockShowCompactionSuccess.mockReset()
    mockSendMessage.mockReset()
    mockActiveGroup = null
    useChatStore.getState().reset(SESSION_ID)
  })

  it('drops the delta when the slot correlation id does not match', () => {
    // Slot belongs to a previous correlation id. A late delta for a
    // superseded correlation id must be ignored even if a Group still
    // happens to be registered with that older id.
    seedStream({ correlationId: 'c-current', isStreaming: true })
    const onDelta = vi.fn()
    mockActiveGroup = { id: 'c-old', onDelta }

    const event = makeEvent({
      type: 'chat.content.delta',
      correlation_id: 'c-old',
      payload: { delta: 'hello' },
    })
    handleChatEvent(
      event,
      mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage,
      SESSION_ID,
    )

    expect(onDelta).not.toHaveBeenCalled()
  })

  it('drops the delta when there is no streaming slot at all', () => {
    // No slot ever seeded — defensive: this used to be allowed through
    // when a Group existed without a slot. Slot-based gating now blocks
    // it before we even look at the Group.
    const onDelta = vi.fn()
    mockActiveGroup = { id: 'c1', onDelta }

    const event = makeEvent({
      type: 'chat.content.delta',
      correlation_id: 'c1',
      payload: { delta: 'hello' },
    })
    handleChatEvent(
      event,
      mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage,
      SESSION_ID,
    )

    expect(onDelta).not.toHaveBeenCalled()
  })

  it('dispatches the delta to the Group when slot and Group both match', () => {
    seedStream({ correlationId: 'c1', isStreaming: true })
    const onDelta = vi.fn()
    mockActiveGroup = { id: 'c1', onDelta }

    const event = makeEvent({
      type: 'chat.content.delta',
      correlation_id: 'c1',
      payload: { delta: 'hello' },
    })
    handleChatEvent(
      event,
      mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage,
      SESSION_ID,
    )

    expect(onDelta).toHaveBeenCalledWith('hello')
  })
})

describe('useChatStream — CHAT_COMPACTION_COMPLETED toast suppression (Fix 21)', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockShowCompactionSuccess.mockReset()
    mockSendMessage.mockReset()
    mockActiveGroup = null
    useChatStore.getState().reset(SESSION_ID)
  })

  function makeCompletedEvent(correlationId: string): BaseEvent {
    return makeEvent({
      type: 'chat.compaction.completed',
      correlation_id: correlationId,
      payload: {
        session_id: SESSION_ID,
        checkpoint: {
          id: 'cp1',
          created_at: new Date().toISOString(),
          model_unique_id: 'm:1',
          summary_markdown: '',
          last_message_id_before: 'mid-before',
          tail_start_message_id: 'mid-after',
          tokens_before: 1000,
          tokens_after: 200,
          tail_token_count: 100,
          prev_checkpoint_id: null,
        },
        tokens_saved: 1234,
        truncated_message_count: 0,
      },
    })
  }

  it('shows the success toast normally when the soft-timeout did NOT fire', () => {
    handleChatEvent(
      makeCompletedEvent('corr-fast'),
      mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage,
      SESSION_ID,
    )
    expect(mockShowCompactionSuccess).toHaveBeenCalledTimes(1)
  })

  it('suppresses the success toast when the soft-timeout fired for this correlation id', () => {
    useChatStore.getState().markCompactionTimedOut('corr-slow')
    handleChatEvent(
      makeCompletedEvent('corr-slow'),
      mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage,
      SESSION_ID,
    )
    expect(mockShowCompactionSuccess).not.toHaveBeenCalled()
    // The sentinel is consumed once read so future events do not stay
    // suppressed forever (e.g. a retry path).
    expect(
      useChatStore.getState().compactionTimedOutCorrelationIds.has('corr-slow'),
    ).toBe(false)
  })
})
