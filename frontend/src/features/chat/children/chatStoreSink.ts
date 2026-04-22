import type { GroupChild } from '../responseTaskGroup'

/**
 * Minimum shape of the chat store consumed by the sink. Keeps this module
 * free of imports from the concrete Zustand store so tests can inject a
 * plain mock.
 */
export interface ChatStoreLike {
  startStreaming(correlationId: string): void
  appendStreamingContent(delta: string): void
  cancelStreaming(): void
}

export interface ChatStoreSinkOpts {
  sessionId: string
  correlationId: string
  chatStore: ChatStoreLike
}

export function createChatStoreSink(opts: ChatStoreSinkOpts): GroupChild {
  const prefix = `[chatStoreSink ${opts.correlationId.slice(0, 8)}]`

  return {
    name: 'chatStoreSink',

    onDelta(delta: string, token: string): void {
      if (token !== opts.correlationId) {
        console.debug(`${prefix} drop delta (token mismatch)`)
        return
      }
      opts.chatStore.appendStreamingContent(delta)
    },

    onStreamEnd(token: string): Promise<void> {
      if (token !== opts.correlationId) return Promise.resolve()
      // The actual finalisation of the streamed message (moving streamingContent
      // into the message list) is driven by CHAT_STREAM_ENDED in useChatStream
      // — see Task 9. This sink resolves immediately because for text-mode
      // there is nothing to drain.
      return Promise.resolve()
    },

    onCancel(_reason, token: string): void {
      if (token !== opts.correlationId) return
      // Deliberately a no-op. The CHAT_STREAM_ENDED handler in useChatStream is
      // authoritative for finalize-vs-cancel — it decides based on the backend's
      // persisted partial content (message_id + content). Calling cancelStreaming()
      // here would erase streamingContent before the handler can read it, causing
      // the partial message to be lost.
    },

    teardown(): void {},
  }
}
