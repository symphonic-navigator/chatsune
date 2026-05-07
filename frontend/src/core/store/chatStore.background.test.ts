import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from './chatStore'

describe('chatStore — session-scoped streaming state', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  it('startStreaming(sessionId) writes into streamsBySession', () => {
    const { startStreaming, getStreamFor } = useChatStore.getState()
    startStreaming('cor-1', { sessionId: 'session-A' })
    const stream = getStreamFor('session-A')
    expect(stream).not.toBeNull()
    expect(stream?.isStreaming).toBe(true)
    expect(stream?.correlationId).toBe('cor-1')
  })

  it('two sessions stream independently', () => {
    const { startStreaming, appendStreamingContent, getStreamFor } =
      useChatStore.getState()

    startStreaming('cor-A', { sessionId: 'session-A' })
    startStreaming('cor-B', { sessionId: 'session-B' })

    appendStreamingContent('hello A', { sessionId: 'session-A' })
    appendStreamingContent('hello B', { sessionId: 'session-B' })

    expect(getStreamFor('session-A')?.streamingContent).toBe('hello A')
    expect(getStreamFor('session-B')?.streamingContent).toBe('hello B')
  })

  it('reset(sessionId) preserves stream slots for ALL sessions, including the target', () => {
    const { startStreaming, reset, getStreamFor } = useChatStore.getState()
    startStreaming('cor-A', { sessionId: 'session-A' })
    startStreaming('cor-B', { sessionId: 'session-B' })

    reset('session-A')

    expect(getStreamFor('session-A')?.isStreaming).toBe(true)
    expect(getStreamFor('session-B')?.isStreaming).toBe(true)
  })

  it('reset() with no argument wipes every stream slot', () => {
    const { startStreaming, reset, getStreamFor } = useChatStore.getState()
    startStreaming('cor-A', { sessionId: 'session-A' })
    startStreaming('cor-B', { sessionId: 'session-B' })

    reset()

    expect(getStreamFor('session-A')).toBeNull()
    expect(getStreamFor('session-B')).toBeNull()
  })

  it('finishStreaming clears the slot for that session', () => {
    const { startStreaming, finishStreaming, getStreamFor } =
      useChatStore.getState()
    startStreaming('cor-A', { sessionId: 'session-A' })
    finishStreaming(
      { id: 'm1', role: 'assistant', content: 'done', token_count: 1 } as any,
      'green',
      0,
      0,
      0,
      undefined,
      { sessionId: 'session-A' },
    )
    expect(getStreamFor('session-A')).toBeNull()
  })
})
