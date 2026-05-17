import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'
import { handleChatEvent } from '../useChatStream'
import type { BaseEvent } from '../../../core/types/events'
import type { ChatMessageDto } from '../../../core/api/chat'

// Spec: ``devdocs/specs/2026-05-17-frontend-race-fixes-design.md`` d-6.
// CHAT_MESSAGE_CREATED handling has three fallbacks:
//   0. exact match on the current tab's ``client_message_id``
//   1. (new) exact content match against an optimistic user entry
//   2. unconditional append
//
// Branch forks, second-tab echoes, and ChatGPT replay all produce
// real user docs without THIS tab's ``client_message_id`` but with
// content that matches a still-pending optimistic entry — fallback 1
// dedups them instead of letting fallback 2 double-display.

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: {
    getState: () => ({ addNotification: vi.fn() }),
  },
}))

const mockSendMessage = vi.fn()
const SESSION_ID = 'sess-dedup'

function makeMessageCreatedEvent(payload: Record<string, unknown>): BaseEvent {
  return {
    id: 'evt-mc-1',
    type: 'chat.message.created',
    sequence: 1,
    scope: `session:${SESSION_ID}`,
    correlation_id: 'corr-1',
    timestamp: new Date().toISOString(),
    payload: { session_id: SESSION_ID, ...payload },
  } as unknown as BaseEvent
}

function optimisticUser(id: string, content: string): ChatMessageDto {
  return {
    id,
    session_id: SESSION_ID,
    role: 'user',
    content,
    thinking: null,
    token_count: content.length,
    attachments: null,
    web_search_context: null,
    knowledge_context: null,
    pti_overflow: null,
    created_at: new Date().toISOString(),
    is_optimistic: true,
  } as unknown as ChatMessageDto
}

describe('useChatStream — CHAT_MESSAGE_CREATED dedup fallback (d-6)', () => {
  beforeEach(() => {
    useChatStore.getState().reset(SESSION_ID)
    useChatStore.setState({ activeSessionId: SESSION_ID } as never)
  })

  it('fallback 0: swap by client_message_id when supplied', () => {
    useChatStore.getState().setMessages([optimisticUser('opt-a', 'Hello world')])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-a',
        client_message_id: 'opt-a',
        role: 'user',
        content: 'Hello world',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0].id).toBe('real-a')
    expect(messages[0].is_optimistic).toBe(false)
  })

  it('fallback 1: dedup by exact content when no client_message_id', () => {
    useChatStore.getState().setMessages([optimisticUser('opt-b', 'Hello world')])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-b',
        role: 'user',
        content: 'Hello world',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0].id).toBe('real-b')
    expect(messages[0].is_optimistic).toBe(false)
  })

  it('fallback 1: dedup by exact content when client_message_id does not match', () => {
    useChatStore.getState().setMessages([optimisticUser('opt-c', 'Hello world')])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-c',
        client_message_id: 'opt-WRONG',
        role: 'user',
        content: 'Hello world',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0].id).toBe('real-c')
    expect(messages[0].is_optimistic).toBe(false)
  })

  it('fallback 2: append when no optimistic entry exists', () => {
    useChatStore.getState().setMessages([])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-d',
        role: 'user',
        content: 'Hello world',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0].id).toBe('real-d')
  })

  it('fallback 2: append when optimistic content differs', () => {
    useChatStore.getState().setMessages([optimisticUser('opt-e', 'Different')])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-e',
        role: 'user',
        content: 'Hello world',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    // Both the optimistic and the real msg stay — they are genuinely
    // distinct, the optimistic is collected by its own future
    // CHAT_MESSAGE_CREATED echo.
    expect(messages).toHaveLength(2)
    expect(messages.map((m) => m.id)).toContain('opt-e')
    expect(messages.map((m) => m.id)).toContain('real-e')
  })

  it('does not dedup an assistant message against an optimistic user with matching content', () => {
    // Pathological but cheap to guard: a user might have typed the
    // same string the assistant later produces. role must match too.
    useChatStore.getState().setMessages([optimisticUser('opt-f', 'hi')])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-f',
        role: 'assistant',
        content: 'hi',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(2)
    expect(messages.find((m) => m.id === 'opt-f')?.is_optimistic).toBe(true)
    expect(messages.find((m) => m.id === 'real-f')?.role).toBe('assistant')
  })

  it('does not collapse two real messages with matching content', () => {
    // Defensive: ``is_optimistic !== true`` gate. If the store somehow
    // contains a real user message with the same content, the new
    // real message must still append rather than overwrite.
    const real = { ...optimisticUser('real-prev', 'Hello'), is_optimistic: false }
    useChatStore.getState().setMessages([real as ChatMessageDto])
    handleChatEvent(
      makeMessageCreatedEvent({
        message_id: 'real-new',
        role: 'user',
        content: 'Hello',
      }),
      mockSendMessage,
      SESSION_ID,
    )
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(2)
  })
})
