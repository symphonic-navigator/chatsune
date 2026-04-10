import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'
import type { ChatMessageDto } from '../../../core/api/chat'

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  it('starts with empty state', () => {
    const state = useChatStore.getState()
    expect(state.messages).toEqual([])
    expect(state.isStreaming).toBe(false)
    expect(state.correlationId).toBeNull()
    expect(state.streamingContent).toBe('')
    expect(state.streamingThinking).toBe('')
    expect(state.contextStatus).toBe('green')
  })

  it('setMessages replaces messages', () => {
    const msgs: ChatMessageDto[] = [{
      id: '1', session_id: 's1', role: 'user', content: 'hello',
      thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 5, created_at: '2026-01-01T00:00:00Z',
    }]
    useChatStore.getState().setMessages(msgs)
    expect(useChatStore.getState().messages).toEqual(msgs)
  })

  it('appendStreamingContent accumulates deltas', () => {
    const { startStreaming, appendStreamingContent } = useChatStore.getState()
    startStreaming('corr-1')
    appendStreamingContent('Hello ')
    appendStreamingContent('world')
    expect(useChatStore.getState().streamingContent).toBe('Hello world')
  })

  it('appendStreamingThinking accumulates deltas', () => {
    const { startStreaming, appendStreamingThinking } = useChatStore.getState()
    startStreaming('corr-1')
    appendStreamingThinking('Let me think...')
    appendStreamingThinking(' about this.')
    expect(useChatStore.getState().streamingThinking).toBe('Let me think... about this.')
  })

  it('finishStreaming assembles final message and resets streaming state', () => {
    const { startStreaming, appendStreamingContent, appendStreamingThinking, finishStreaming } = useChatStore.getState()
    startStreaming('corr-1')
    appendStreamingContent('Answer')
    appendStreamingThinking('Reasoning')
    finishStreaming({
      id: 'msg-1', session_id: 's1', role: 'assistant', content: 'Answer',
      thinking: 'Reasoning', web_search_context: null, attachments: null, knowledge_context: null, token_count: 10, created_at: '2026-01-01T00:00:00Z',
    }, 'yellow', 0.55)

    const state = useChatStore.getState()
    expect(state.isStreaming).toBe(false)
    expect(state.streamingContent).toBe('')
    expect(state.streamingThinking).toBe('')
    expect(state.messages[state.messages.length - 1]?.content).toBe('Answer')
    expect(state.contextStatus).toBe('yellow')
    expect(state.contextFillPercentage).toBe(0.55)
  })

  it('cancelStreaming resets streaming state', () => {
    const { startStreaming, appendStreamingContent, cancelStreaming } = useChatStore.getState()
    startStreaming('corr-1')
    appendStreamingContent('Partial ans')
    cancelStreaming()
    const state = useChatStore.getState()
    expect(state.isStreaming).toBe(false)
    expect(state.streamingContent).toBe('')
  })

  it('truncateAfter removes messages after given ID', () => {
    const msgs: ChatMessageDto[] = [
      { id: '1', session_id: 's1', role: 'user', content: 'a', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:00Z' },
      { id: '2', session_id: 's1', role: 'assistant', content: 'b', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:01Z' },
      { id: '3', session_id: 's1', role: 'user', content: 'c', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:02Z' },
      { id: '4', session_id: 's1', role: 'assistant', content: 'd', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:03Z' },
    ]
    useChatStore.getState().setMessages(msgs)
    useChatStore.getState().truncateAfter('2')
    expect(useChatStore.getState().messages.map(m => m.id)).toEqual(['1', '2'])
  })

  it('updateMessage replaces content of existing message', () => {
    const msgs: ChatMessageDto[] = [
      { id: '1', session_id: 's1', role: 'user', content: 'old', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:00Z' },
    ]
    useChatStore.getState().setMessages(msgs)
    useChatStore.getState().updateMessage('1', 'new', 3)
    expect(useChatStore.getState().messages[0].content).toBe('new')
    expect(useChatStore.getState().messages[0].token_count).toBe(3)
  })

  it('deleteMessage removes message by ID', () => {
    const msgs: ChatMessageDto[] = [
      { id: '1', session_id: 's1', role: 'user', content: 'a', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:00Z' },
      { id: '2', session_id: 's1', role: 'assistant', content: 'b', thinking: null, web_search_context: null, attachments: null, knowledge_context: null, token_count: 1, created_at: '2026-01-01T00:00:01Z' },
    ]
    useChatStore.getState().setMessages(msgs)
    useChatStore.getState().deleteMessage('2')
    expect(useChatStore.getState().messages).toHaveLength(1)
    expect(useChatStore.getState().messages[0].id).toBe('1')
  })

  it('setError stores error and clearError clears it', () => {
    useChatStore.getState().setError({
      errorCode: 'provider_unavailable',
      recoverable: true,
      userMessage: 'Provider is down',
    })
    expect(useChatStore.getState().error?.errorCode).toBe('provider_unavailable')
    useChatStore.getState().clearError()
    expect(useChatStore.getState().error).toBeNull()
  })

  it('reset stores activeSessionId', () => {
    useChatStore.getState().reset('session-abc')
    expect(useChatStore.getState().activeSessionId).toBe('session-abc')
  })

  it('reset without sessionId clears activeSessionId', () => {
    useChatStore.getState().reset('session-abc')
    useChatStore.getState().reset()
    expect(useChatStore.getState().activeSessionId).toBeNull()
  })

  it('streamingSlow defaults to false', () => {
    const state = useChatStore.getState()
    expect(state.streamingSlow).toBe(false)
  })

  it('setStreamingSlow sets the flag to true', () => {
    useChatStore.getState().setStreamingSlow(true)
    expect(useChatStore.getState().streamingSlow).toBe(true)
  })

  it('appendStreamingContent clears streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().appendStreamingContent('hi')
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })

  it('appendStreamingThinking clears streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().appendStreamingThinking('thought')
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })

  it('startStreaming resets streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().startStreaming('corr-2')
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })

  it('cancelStreaming clears streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().cancelStreaming()
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })
})
