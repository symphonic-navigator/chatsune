import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'
import type { ChatMessageDto } from '../../../core/api/chat'

const SESSION_ID = 'session-test'
const opts = { sessionId: SESSION_ID }

describe('chatStore', () => {
  beforeEach(() => {
    // Reset to a known sessionId so finishStreaming knows the active session
    // and appends the persisted message into the visible transcript.
    useChatStore.getState().reset(SESSION_ID)
  })

  it('starts with empty state', () => {
    const state = useChatStore.getState()
    expect(state.messages).toEqual([])
    expect(state.getStreamFor(SESSION_ID)).toBeNull()
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
    const { startStreaming, appendStreamingContent, getStreamFor } = useChatStore.getState()
    startStreaming('corr-1', opts)
    appendStreamingContent('Hello ', opts)
    appendStreamingContent('world', opts)
    expect(getStreamFor(SESSION_ID)?.streamingContent).toBe('Hello world')
  })

  it('appendStreamingThinking accumulates deltas', () => {
    const { startStreaming, appendStreamingThinking, getStreamFor } = useChatStore.getState()
    startStreaming('corr-1', opts)
    appendStreamingThinking('Let me think...', opts)
    appendStreamingThinking(' about this.', opts)
    expect(getStreamFor(SESSION_ID)?.streamingThinking).toBe('Let me think... about this.')
  })

  it('finishStreaming assembles final message and resets streaming state', () => {
    const { startStreaming, appendStreamingContent, appendStreamingThinking, finishStreaming, getStreamFor } = useChatStore.getState()
    startStreaming('corr-1', opts)
    appendStreamingContent('Answer', opts)
    appendStreamingThinking('Reasoning', opts)
    finishStreaming({
      id: 'msg-1', session_id: 's1', role: 'assistant', content: 'Answer',
      thinking: 'Reasoning', web_search_context: null, attachments: null, knowledge_context: null, token_count: 10, created_at: '2026-01-01T00:00:00Z',
    }, 'yellow', 0.55, 0, 0, undefined, opts)

    const state = useChatStore.getState()
    expect(getStreamFor(SESSION_ID)).toBeNull()
    expect(state.messages[state.messages.length - 1]?.content).toBe('Answer')
    expect(state.contextStatus).toBe('yellow')
    expect(state.contextFillPercentage).toBe(0.55)
  })

  it('cancelStreaming resets streaming state', () => {
    const { startStreaming, appendStreamingContent, cancelStreaming, getStreamFor } = useChatStore.getState()
    startStreaming('corr-1', opts)
    appendStreamingContent('Partial ans', opts)
    cancelStreaming(opts)
    expect(getStreamFor(SESSION_ID)).toBeNull()
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

  it('streamingSlow defaults to false (no slot)', () => {
    const state = useChatStore.getState()
    expect(state.getStreamFor(SESSION_ID)).toBeNull()
  })

  it('setStreamingSlow sets the flag to true', () => {
    useChatStore.getState().setStreamingSlow(true, opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)?.streamingSlow).toBe(true)
  })

  it('appendStreamingContent clears streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true, opts)
    useChatStore.getState().appendStreamingContent('hi', opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)?.streamingSlow).toBe(false)
  })

  it('appendStreamingThinking clears streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true, opts)
    useChatStore.getState().appendStreamingThinking('thought', opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)?.streamingSlow).toBe(false)
  })

  it('startStreaming resets streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true, opts)
    useChatStore.getState().startStreaming('corr-2', opts)
    expect(useChatStore.getState().getStreamFor(SESSION_ID)?.streamingSlow).toBe(false)
  })

  it('cancelStreaming clears streamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true, opts)
    useChatStore.getState().cancelStreaming(opts)
    // After cancelStreaming, the slot is cleared entirely.
    expect(useChatStore.getState().getStreamFor(SESSION_ID)).toBeNull()
  })
})

describe('useChatStore — activeProjectId', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  it('starts as null', () => {
    expect(useChatStore.getState().activeProjectId).toBeNull()
  })

  it('setActiveProjectId stores a project id', () => {
    useChatStore.getState().setActiveProjectId('p-1')
    expect(useChatStore.getState().activeProjectId).toBe('p-1')
  })

  it('setActiveProjectId(null) clears it', () => {
    useChatStore.getState().setActiveProjectId('p-1')
    useChatStore.getState().setActiveProjectId(null)
    expect(useChatStore.getState().activeProjectId).toBeNull()
  })

  it('reset() clears active project', () => {
    useChatStore.getState().setActiveProjectId('p-1')
    useChatStore.getState().reset()
    expect(useChatStore.getState().activeProjectId).toBeNull()
  })
})
