import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from './chatStore'
import type { ChatMessageDto, TimelineEntry } from '../api/chat'

const SESSION_ID = 'session-test'
const opts = { sessionId: SESSION_ID }

function reset() {
  // Reset to a known sessionId so finishStreaming knows the active session
  // and appends the persisted message into the visible transcript.
  useChatStore.getState().reset(SESSION_ID)
}

function createFinalMessage(): ChatMessageDto {
  return {
    id: 'm1',
    session_id: 's1',
    role: 'assistant',
    content: 'hi',
    thinking: null,
    token_count: 0,
    attachments: null,
    web_search_context: null,
    knowledge_context: null,
    created_at: new Date().toISOString(),
    status: 'completed',
  }
}

describe('chatStore — streaming events and refusal slices', () => {
  beforeEach(reset)

  it('appendStreamingEvent appends entries with monotonic seq', () => {
    const a: TimelineEntry = {
      kind: 'artefact',
      seq: 0,
      ref: {
        artefact_id: 'a1',
        handle: 'h1',
        title: 't1',
        artefact_type: 'code',
        operation: 'create',
      },
    }
    const b: TimelineEntry = {
      kind: 'web_search',
      seq: 0,
      items: [{ title: 't', url: 'u', snippet: 's' }],
    }
    useChatStore.getState().appendStreamingEvent(a, opts)
    useChatStore.getState().appendStreamingEvent(b, opts)
    const events = useChatStore.getState().getStreamFor(SESSION_ID)?.streamingEvents ?? []
    expect(events).toHaveLength(2)
    expect(events[0].seq).toBe(0)
    expect(events[1].seq).toBe(1)
    expect(events[0].kind).toBe('artefact')
    expect(events[1].kind).toBe('web_search')
  })

  it('appendStreamingEvent ignores caller-supplied seq', () => {
    useChatStore.getState().appendStreamingEvent({
      kind: 'knowledge_search',
      seq: 999,
      items: [],
    }, opts)
    const events = useChatStore.getState().getStreamFor(SESSION_ID)?.streamingEvents ?? []
    expect(events[0].seq).toBe(0)
  })

  it('setStreamingRefusalText sets the refusal text', () => {
    useChatStore.getState().setStreamingRefusalText('declined', opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)?.streamingRefusalText).toBe('declined')
  })

  it('finishStreaming clears the slot (and thus streamingEvents/refusalText)', () => {
    useChatStore.getState().appendStreamingEvent({
      kind: 'artefact',
      seq: 0,
      ref: {
        artefact_id: 'a1',
        handle: 'h1',
        title: 't1',
        artefact_type: 'code',
        operation: 'create',
      },
    }, opts)
    useChatStore.getState().setStreamingRefusalText('declined', opts)

    const finalMessage = createFinalMessage()
    useChatStore.getState().finishStreaming(finalMessage, 'green', 0, 0, 0, undefined, opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)).toBeNull()
  })

  it('startStreaming resets streamingEvents', () => {
    useChatStore.getState().appendStreamingEvent({
      kind: 'web_search',
      seq: 0,
      items: [{ title: 't', url: 'u', snippet: 's' }],
    }, opts)
    useChatStore.getState().startStreaming('corr-2', opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)?.streamingEvents).toEqual([])
  })

  it('cancelStreaming resets streamingEvents (slot cleared)', () => {
    useChatStore.getState().appendStreamingEvent({
      kind: 'web_search',
      seq: 0,
      items: [{ title: 't', url: 'u', snippet: 's' }],
    }, opts)
    useChatStore.getState().cancelStreaming(opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)).toBeNull()
  })
})

describe('appendToolCallDelta', () => {
  it('creates a new streaming slot on first delta', () => {
    const store = useChatStore.getState()
    store.startStreaming('corr-1', { sessionId: 'sess-1' })
    store.appendToolCallDelta(
      'call_x', 0, 'search', '{"q', { sessionId: 'sess-1' },
    )
    const slot = store.getStreamFor('sess-1')!.streamingToolCalls.get('call_x')
    expect(slot).toBeDefined()
    expect(slot!.toolName).toBe('search')
    expect(slot!.argsBuffer).toBe('{"q')
    expect(slot!.charCount).toBe(3)
    expect(slot!.phase).toBe('streaming')
  })

  it('appends to existing slot and updates counters', () => {
    const store = useChatStore.getState()
    store.startStreaming('corr-2', { sessionId: 'sess-2' })
    store.appendToolCallDelta('call_y', 0, 'f', '{"a', { sessionId: 'sess-2' })
    store.appendToolCallDelta('call_y', 0, null, '":"b"}', { sessionId: 'sess-2' })
    const slot = store.getStreamFor('sess-2')!.streamingToolCalls.get('call_y')!
    expect(slot.argsBuffer).toBe('{"a":"b"}')
    expect(slot.charCount).toBe(9)
    expect(slot.toolName).toBe('f')
  })

  it('sets toolName when supplied in a later delta', () => {
    const store = useChatStore.getState()
    store.startStreaming('corr-3', { sessionId: 'sess-3' })
    store.appendToolCallDelta('call_z', 0, null, '', { sessionId: 'sess-3' })
    store.appendToolCallDelta('call_z', 0, 'lateName', 'x', { sessionId: 'sess-3' })
    const slot = store.getStreamFor('sess-3')!.streamingToolCalls.get('call_z')!
    expect(slot.toolName).toBe('lateName')
  })
})

describe('promoteToolCallToExecuting', () => {
  it('promotes an existing streaming slot to executing', () => {
    const store = useChatStore.getState()
    store.startStreaming('c1', { sessionId: 's1' })
    store.appendToolCallDelta('call_x', 0, 'search', '{}', { sessionId: 's1' })
    store.promoteToolCallToExecuting(
      'call_x', 'search', { q: 'hi' }, { sessionId: 's1' },
    )
    const slot = store.getStreamFor('s1')!.streamingToolCalls.get('call_x')!
    expect(slot.phase).toBe('executing')
    expect(slot.parsedArguments).toEqual({ q: 'hi' })
  })

  it('creates a new executing slot when streaming slot is absent (Ollama path)', () => {
    const store = useChatStore.getState()
    store.startStreaming('c2', { sessionId: 's2' })
    store.promoteToolCallToExecuting(
      'call_y', 'lookup', { id: 42 }, { sessionId: 's2' },
    )
    const slot = store.getStreamFor('s2')!.streamingToolCalls.get('call_y')!
    expect(slot.phase).toBe('executing')
    expect(slot.toolName).toBe('lookup')
    expect(slot.argsBuffer).toBe('')
    expect(slot.parsedArguments).toEqual({ id: 42 })
  })
})

describe('removeStreamingToolCall', () => {
  it('removes the slot for the given tool_call_id', () => {
    const store = useChatStore.getState()
    store.startStreaming('c1', { sessionId: 's1' })
    store.appendToolCallDelta('call_x', 0, 'search', '{}', { sessionId: 's1' })
    expect(store.getStreamFor('s1')!.streamingToolCalls.has('call_x')).toBe(true)
    store.removeStreamingToolCall('call_x', { sessionId: 's1' })
    expect(store.getStreamFor('s1')!.streamingToolCalls.has('call_x')).toBe(false)
  })

  it('is a no-op when the id does not exist', () => {
    const store = useChatStore.getState()
    store.startStreaming('c2', { sessionId: 's2' })
    expect(() => store.removeStreamingToolCall('nope', { sessionId: 's2' }))
      .not.toThrow()
  })
})

describe('streamingToolCalls cleanup on cancel', () => {
  it('cancelStreaming clears streamingToolCalls', () => {
    const store = useChatStore.getState()
    store.startStreaming('c1', { sessionId: 's1' })
    store.appendToolCallDelta('call_x', 0, 'f', '{}', { sessionId: 's1' })
    store.cancelStreaming({ sessionId: 's1' })
    // cancelStreaming fully removes the slot; getStreamFor returns null and
    // therefore streamingToolCalls is no longer retained. This is a
    // regression guard — if the cancel path ever switches to a partial
    // reset, the slot would still exist and we'd want streamingToolCalls
    // empty, hence the dual-branch assertion.
    const slot = store.getStreamFor('s1')
    expect(slot?.streamingToolCalls.size ?? 0).toBe(0)
  })
})

describe('compaction soft-timeout sentinel', () => {
  beforeEach(() => useChatStore.getState().reset())

  it('markCompactionTimedOut records the correlation id', () => {
    useChatStore.getState().markCompactionTimedOut('corr-A')
    expect(useChatStore.getState().compactionTimedOutCorrelationIds.has('corr-A')).toBe(true)
  })

  it('consumeCompactionTimedOut returns true once and clears the flag', () => {
    useChatStore.getState().markCompactionTimedOut('corr-A')
    expect(useChatStore.getState().consumeCompactionTimedOut('corr-A')).toBe(true)
    // Second call returns false — the flag has been consumed.
    expect(useChatStore.getState().consumeCompactionTimedOut('corr-A')).toBe(false)
    expect(useChatStore.getState().compactionTimedOutCorrelationIds.has('corr-A')).toBe(false)
  })

  it('consumeCompactionTimedOut returns false for an unknown correlation id', () => {
    expect(useChatStore.getState().consumeCompactionTimedOut('never-marked')).toBe(false)
  })

  it('markCompactionTimedOut is idempotent', () => {
    useChatStore.getState().markCompactionTimedOut('corr-A')
    useChatStore.getState().markCompactionTimedOut('corr-A')
    expect(useChatStore.getState().compactionTimedOutCorrelationIds.size).toBe(1)
  })
})
