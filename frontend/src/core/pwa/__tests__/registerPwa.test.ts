import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { reloadWhenIdle } from '../registerPwa'
import { useChatStore, type SessionStreamingState } from '../../store/chatStore'
import { useConversationModeStore } from '../../../features/voice/stores/conversationModeStore'

type StoreState = ReturnType<typeof useChatStore.getState>
type ConvModeState = ReturnType<typeof useConversationModeStore.getState>

const STREAMING_SLOT: SessionStreamingState = {
  isWaitingForResponse: false,
  isStreaming: true,
  correlationId: 'c-test',
  streamingContent: '',
  streamingThinking: '',
  streamingEvents: [],
  streamingRefusalText: null,
  streamingToolCalls: new Map(),
  visionDescriptions: {},
  streamingSlow: false,
}

function setStreaming(active: boolean): void {
  // Streaming state moved into per-session slots in Task 5; an active
  // stream is represented by a single slot in `streamsBySession`. The
  // PWA reload trigger checks `slot.isStreaming` for any session, so a
  // single test fixture session is enough.
  const map = new Map<string, SessionStreamingState>()
  if (active) map.set('s-test', STREAMING_SLOT)
  useChatStore.setState({ streamsBySession: map } as Partial<StoreState> as StoreState)
}

describe('reloadWhenIdle', () => {
  let reloadSpy: () => void
  beforeEach(() => {
    vi.useFakeTimers()
    reloadSpy = vi.fn()
    setStreaming(false)
    useConversationModeStore.setState({ active: false } as Partial<ConvModeState> as ConvModeState)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reloads immediately when idle', () => {
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('defers while streaming', () => {
    setStreaming(true)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('defers while conversation mode is active', () => {
    useConversationModeStore.setState({ active: true } as Partial<ConvModeState> as ConvModeState)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('reloads after streaming ends and the settle window elapses', () => {
    setStreaming(true)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()

    setStreaming(false)
    // Still deferred during the 500ms settle window.
    expect(reloadSpy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('cancels the settle timer if a new stream starts inside the window', () => {
    setStreaming(true)
    reloadWhenIdle(reloadSpy)

    setStreaming(false)
    vi.advanceTimersByTime(200)
    setStreaming(true)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).not.toHaveBeenCalled()

    setStreaming(false)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('waits for both conversation mode and streaming to be false', () => {
    setStreaming(true)
    useConversationModeStore.setState({ active: true } as Partial<ConvModeState> as ConvModeState)
    reloadWhenIdle(reloadSpy)

    setStreaming(false)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).not.toHaveBeenCalled() // conversation still active

    useConversationModeStore.setState({ active: false } as Partial<ConvModeState> as ConvModeState)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })
})
