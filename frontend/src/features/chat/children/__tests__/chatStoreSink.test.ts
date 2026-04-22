import { describe, it, expect, vi } from 'vitest'
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
    expect(store.appendStreamingContent).toHaveBeenCalledWith('hello')
  })

  it('onDelta drops when token does not match', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onDelta('hello', 'other-token')
    expect(store.appendStreamingContent).not.toHaveBeenCalled()
  })

  it('onCancel does NOT call cancelStreaming (CHAT_STREAM_ENDED is authoritative)', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onCancel('user-stop', 'c1')
    expect(store.cancelStreaming).not.toHaveBeenCalled()
  })

  it('onCancel drops when token does not match', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onCancel('user-stop', 'other-token')
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
