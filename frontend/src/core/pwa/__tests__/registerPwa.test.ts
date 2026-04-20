import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { reloadWhenIdle } from '../registerPwa'
import { useChatStore } from '../../store/chatStore'
import { useConversationModeStore } from '../../../features/voice/stores/conversationModeStore'

describe('reloadWhenIdle', () => {
  let reloadSpy: () => void
  beforeEach(() => {
    vi.useFakeTimers()
    reloadSpy = vi.fn()
    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    useConversationModeStore.setState({ active: false } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reloads immediately when idle', () => {
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('defers while streaming', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('defers while conversation mode is active', () => {
    useConversationModeStore.setState({ active: true } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('reloads after streaming ends and the settle window elapses', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    // Still deferred during the 500ms settle window.
    expect(reloadSpy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('cancels the settle timer if a new stream starts inside the window', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    reloadWhenIdle(reloadSpy)

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(200)
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).not.toHaveBeenCalled()

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('waits for both conversation mode and streaming to be false', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    useConversationModeStore.setState({ active: true } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
    reloadWhenIdle(reloadSpy)

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).not.toHaveBeenCalled() // conversation still active

    useConversationModeStore.setState({ active: false } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })
})
