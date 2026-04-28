import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from './chatStore'
import type { ChatMessageDto } from '../api/chat'

function reset() {
  useChatStore.setState({
    streamingArtefactRefs: [],
    streamingRefusalText: null,
    activeToolCalls: [],
  } as any)
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

describe('chatStore — streaming artefact and refusal slices', () => {
  beforeEach(reset)

  it('appendArtefactRef adds to streamingArtefactRefs', () => {
    useChatStore.getState().appendArtefactRef({
      artefact_id: 'a1',
      handle: 'h1',
      title: 't1',
      artefact_type: 'code',
      operation: 'create',
    })
    expect(useChatStore.getState().streamingArtefactRefs).toHaveLength(1)
    expect(useChatStore.getState().streamingArtefactRefs[0].handle).toBe('h1')
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

  it('finishStreaming clears the new streaming fields', () => {
    useChatStore.getState().appendArtefactRef({
      artefact_id: 'a1',
      handle: 'h1',
      title: 't1',
      artefact_type: 'code',
      operation: 'create',
    })
    useChatStore.getState().setStreamingRefusalText('declined')

    const finalMessage = createFinalMessage()
    useChatStore.getState().finishStreaming(finalMessage, 'green', 0)
    expect(useChatStore.getState().streamingArtefactRefs).toEqual([])
    expect(useChatStore.getState().streamingRefusalText).toBeNull()
  })
})
