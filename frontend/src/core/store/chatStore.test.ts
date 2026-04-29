import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from './chatStore'
import type { ChatMessageDto, TimelineEntry } from '../api/chat'

function reset() {
  useChatStore.setState({
    streamingEvents: [],
    streamingRefusalText: null,
    activeToolCalls: [],
  } as Partial<ReturnType<typeof useChatStore.getState>> as ReturnType<typeof useChatStore.getState>)
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
    useChatStore.getState().appendStreamingEvent(a)
    useChatStore.getState().appendStreamingEvent(b)
    const events = useChatStore.getState().streamingEvents
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
    })
    expect(useChatStore.getState().streamingEvents[0].seq).toBe(0)
  })

  it('setStreamingRefusalText sets the refusal text', () => {
    useChatStore.getState().setStreamingRefusalText('declined')
    expect(useChatStore.getState().streamingRefusalText).toBe('declined')
  })

  it('addToolCall is idempotent on tool_call_id', () => {
    const tc = {
      id: 'call_abc',
      toolName: 'lookup',
      arguments: { q: 'first' },
      status: 'running' as const,
    }
    useChatStore.getState().addToolCall(tc)
    // Same id, different arguments — represents a duplicate
    // ToolCallStarted event from a misbehaving upstream stream.
    useChatStore.getState().addToolCall({ ...tc, arguments: { q: 'second' } })
    const calls = useChatStore.getState().activeToolCalls
    expect(calls).toHaveLength(1)
    expect(calls[0].arguments).toEqual({ q: 'second' })
  })

  it('finishStreaming clears streamingEvents and refusal text', () => {
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
    })
    useChatStore.getState().setStreamingRefusalText('declined')

    const finalMessage = createFinalMessage()
    useChatStore.getState().finishStreaming(finalMessage, 'green', 0)
    expect(useChatStore.getState().streamingEvents).toEqual([])
    expect(useChatStore.getState().streamingRefusalText).toBeNull()
  })

  it('startStreaming resets streamingEvents', () => {
    useChatStore.getState().appendStreamingEvent({
      kind: 'web_search',
      seq: 0,
      items: [{ title: 't', url: 'u', snippet: 's' }],
    })
    useChatStore.getState().startStreaming('corr-2')
    expect(useChatStore.getState().streamingEvents).toEqual([])
  })

  it('cancelStreaming resets streamingEvents', () => {
    useChatStore.getState().appendStreamingEvent({
      kind: 'web_search',
      seq: 0,
      items: [{ title: 't', url: 'u', snippet: 's' }],
    })
    useChatStore.getState().cancelStreaming()
    expect(useChatStore.getState().streamingEvents).toEqual([])
  })
})
