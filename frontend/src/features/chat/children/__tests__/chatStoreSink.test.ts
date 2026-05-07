import { describe, it, expect, vi } from 'vitest'
import { useChatStore } from '@/core/store/chatStore'
import { createChatStoreSink } from '../chatStoreSink'

function makeStore() {
  return {
    startStreaming: vi.fn(),
    appendStreamingContent: vi.fn(),
    cancelStreaming: vi.fn(),
    correlationId: null as string | null,
  }
}

describe('chatStoreSink', () => {
  it('onDelta appends content when token matches', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onDelta('hello', 'c1')
    expect(store.appendStreamingContent).toHaveBeenCalledWith('hello', { sessionId: 's1' })
  })

  it('onDelta drops when token does not match', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onDelta('hello', 'other-token')
    expect(store.appendStreamingContent).not.toHaveBeenCalled()
  })

  it('onCancel with user-stop reason calls cancelStreaming on the injected store', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onCancel('user-stop', 'c1')
    expect(store.cancelStreaming).toHaveBeenCalledWith({ sessionId: 's1' })
  })

  it('onCancel with teardown reason leaves the injected store untouched', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onCancel('teardown', 'c1')
    expect(store.cancelStreaming).not.toHaveBeenCalled()
  })

  it('onStreamEnd resolves immediately', async () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    await expect(sink.onStreamEnd('c1')).resolves.toBeUndefined()
  })
})

describe('chatStoreSink teardown semantics', () => {
  it('teardown reason leaves the streaming slot intact for resume', () => {
    useChatStore.getState().reset()
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'session-A' })
    useChatStore.getState().appendStreamingContent('hello', { sessionId: 'session-A' })

    const sink = createChatStoreSink({
      sessionId: 'session-A',
      correlationId: 'cor-1',
      chatStore: useChatStore.getState(),
    })
    sink.onCancel('teardown', 'cor-1')

    expect(useChatStore.getState().getStreamFor('session-A')?.streamingContent).toBe('hello')
    expect(useChatStore.getState().getStreamFor('session-A')?.isStreaming).toBe(true)
  })

  it('user-stop reason clears the streaming slot', () => {
    useChatStore.getState().reset()
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'session-A' })
    useChatStore.getState().appendStreamingContent('hello', { sessionId: 'session-A' })

    const sink = createChatStoreSink({
      sessionId: 'session-A',
      correlationId: 'cor-1',
      chatStore: useChatStore.getState(),
    })
    sink.onCancel('user-stop', 'cor-1')

    expect(useChatStore.getState().getStreamFor('session-A')).toBeNull()
  })
})
