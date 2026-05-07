import type { CancelReason, GroupChild } from '../responseTaskGroup'

/**
 * Minimum shape of the chat store consumed by the sink. Keeps this module
 * free of imports from the concrete Zustand store so tests can inject a
 * plain mock. Each method takes the same `{ sessionId }` opt the underlying
 * store now requires — the sink fills it from `opts.sessionId` so the
 * Group's session id is the single source of truth at the call site.
 */
export interface ChatStoreLike {
  startStreaming(correlationId: string, opts: { sessionId: string }): void
  appendStreamingContent(delta: string, opts: { sessionId: string }): void
  cancelStreaming(opts: { sessionId: string }): void
}

export interface ChatStoreSinkOpts {
  sessionId: string
  correlationId: string
  chatStore: ChatStoreLike
}

export function createChatStoreSink(opts: ChatStoreSinkOpts): GroupChild {
  const prefix = `[chatStoreSink ${opts.correlationId.slice(0, 8)}]`
  const writeOpts = { sessionId: opts.sessionId }

  return {
    name: 'chatStoreSink',

    onDelta(delta: string, token: string): void {
      if (token !== opts.correlationId) {
        console.debug(`${prefix} drop delta (token mismatch)`)
        return
      }
      opts.chatStore.appendStreamingContent(delta, writeOpts)
    },

    onStreamEnd(token: string): Promise<void> {
      if (token !== opts.correlationId) return Promise.resolve()
      // The actual finalisation of the streamed message (moving streamingContent
      // into the message list) is driven by CHAT_STREAM_ENDED in useChatStream
      // — see Task 9. This sink resolves immediately because for text-mode
      // there is nothing to drain.
      return Promise.resolve()
    },

    onCancel(reason: CancelReason, token: string): void {
      // Mismatched token → not our stream. Same defensive check as
      // onDelta and onStreamEnd; cheap insurance against a future
      // multi-session edge case where a stale token reaches the wrong
      // sink and would otherwise wipe the wrong session's slot.
      if (token !== opts.correlationId) return
      // Background-completion semantics: 'teardown' = the UI is
      // unmounting (persona switch, history view, etc.) but the
      // inference is still running on the backend. Leave the streaming
      // slot in place so a future remount of the same session resumes
      // the live stream. Every other reason is a definitive end (user
      // pressed Stop, a new send superseded this one, etc.) — wipe the
      // slot now so the partial bubble disappears immediately on user
      // intent, without waiting for CHAT_STREAM_ENDED from the server.
      if (reason === 'teardown') return
      opts.chatStore.cancelStreaming(writeOpts)
    },

    teardown(): void {},
  }
}
