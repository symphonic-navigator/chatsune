import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'
import { handleChatEvent } from '../useChatStream'
import type { BaseEvent } from '../../../core/types/events'
import type { ChatMessageDto } from '../../../core/api/chat'

// Spec: ``devdocs/specs/2026-05-17-frontend-race-fixes-design.md`` d-13.
// While ChatView is waiting for ``chatApi.getMessages`` to return, any
// WS events targeting the same session must be queued — not applied on
// top of state that's about to be replaced. ``endReconciliation`` drains
// the queue through ``handleChatEvent`` so every event takes the path
// it would have taken live.

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: {
    getState: () => ({ addNotification: vi.fn() }),
  },
}))

const mockSendMessage = vi.fn()
const SESSION_A = 'sess-A'
const SESSION_B = 'sess-B'

function makeMessageCreatedEvent(
  sessionId: string,
  payload: Record<string, unknown>,
): BaseEvent {
  return {
    id: `evt-mc-${sessionId}`,
    type: 'chat.message.created',
    sequence: 1,
    scope: `session:${sessionId}`,
    correlation_id: 'corr-1',
    timestamp: new Date().toISOString(),
    payload: { session_id: sessionId, ...payload },
  } as unknown as BaseEvent
}

function makeMessage(id: string, sessionId: string, content: string): ChatMessageDto {
  return {
    id,
    session_id: sessionId,
    role: 'user',
    content,
    thinking: null,
    token_count: content.length,
    attachments: null,
    web_search_context: null,
    knowledge_context: null,
    pti_overflow: null,
    created_at: new Date().toISOString(),
  } as unknown as ChatMessageDto
}

describe('useChatStream — reconciliation queue (d-13)', () => {
  beforeEach(() => {
    useChatStore.getState().reset(SESSION_A)
    useChatStore.setState({
      activeSessionId: SESSION_A,
      reconciling: {},
    } as never)
  })

  it('events arriving during the window get queued, not dispatched', () => {
    useChatStore.getState().beginReconciliation(SESSION_A)
    handleChatEvent(
      makeMessageCreatedEvent(SESSION_A, {
        message_id: 'real-1',
        role: 'user',
        content: 'mid-rest',
      }),
      mockSendMessage,
      SESSION_A,
    )
    // The message must NOT be in the store yet — the dispatcher saw
    // the open window and queued the event instead.
    expect(useChatStore.getState().messages).toHaveLength(0)
    expect(useChatStore.getState().reconciling[SESSION_A]).toHaveLength(1)
  })

  it('endReconciliation drains queued events through the regular dispatcher', () => {
    useChatStore.getState().beginReconciliation(SESSION_A)
    handleChatEvent(
      makeMessageCreatedEvent(SESSION_A, {
        message_id: 'real-2',
        role: 'user',
        content: 'queued',
      }),
      mockSendMessage,
      SESSION_A,
    )
    // Now the REST snapshot lands. Apply the bundle, then drain.
    useChatStore
      .getState()
      .setMessages([makeMessage('rest-1', SESSION_A, 'from-bundle')])
    useChatStore
      .getState()
      .endReconciliation(SESSION_A, (e) =>
        handleChatEvent(e, mockSendMessage, SESSION_A),
      )
    const messages = useChatStore.getState().messages
    expect(messages.map((m) => m.id)).toEqual(['rest-1', 'real-2'])
    expect(useChatStore.getState().reconciling[SESSION_A]).toBeUndefined()
  })

  it('events for OTHER sessions flow through unimpeded during a window', () => {
    useChatStore.getState().beginReconciliation(SESSION_A)
    // Hook is bound to SESSION_A; an event for SESSION_B is normally
    // filtered out by the session-id guard in the handler, but the
    // reconcile-queue logic must not intercept it for SESSION_B's queue.
    handleChatEvent(
      makeMessageCreatedEvent(SESSION_B, {
        message_id: 'b-1',
        role: 'user',
        content: 'other session',
      }),
      mockSendMessage,
      SESSION_A,
    )
    // Nothing was queued for SESSION_A.
    expect(useChatStore.getState().reconciling[SESSION_A]).toHaveLength(0)
    // SESSION_B is not reconciling, so no queue for it either.
    expect(useChatStore.getState().reconciling[SESSION_B]).toBeUndefined()
  })

  it('cancellation: endReconciliation with a no-op handler drops the queue', () => {
    useChatStore.getState().beginReconciliation(SESSION_A)
    handleChatEvent(
      makeMessageCreatedEvent(SESSION_A, {
        message_id: 'real-3',
        role: 'user',
        content: 'doomed',
      }),
      mockSendMessage,
      SESSION_A,
    )
    expect(useChatStore.getState().reconciling[SESSION_A]).toHaveLength(1)
    useChatStore.getState().endReconciliation(SESSION_A, () => {})
    expect(useChatStore.getState().reconciling[SESSION_A]).toBeUndefined()
    // Nothing was applied to the store either.
    expect(useChatStore.getState().messages).toHaveLength(0)
  })

  it('drained events take the same path as live events (dedup-by-content still applies)', () => {
    // Seat an optimistic user message first — emulates the user
    // having typed AND sent before the WS echo for their own send
    // arrives during the REST window.
    useChatStore.getState().setMessages([
      {
        id: 'opt-1',
        session_id: SESSION_A,
        role: 'user',
        content: 'hi there',
        thinking: null,
        token_count: 8,
        attachments: null,
        web_search_context: null,
        knowledge_context: null,
        pti_overflow: null,
        created_at: new Date().toISOString(),
        is_optimistic: true,
      } as unknown as ChatMessageDto,
    ])
    useChatStore.getState().beginReconciliation(SESSION_A)
    handleChatEvent(
      makeMessageCreatedEvent(SESSION_A, {
        message_id: 'real-1',
        role: 'user',
        content: 'hi there',
        // No client_message_id — exercises fallback 1.
      }),
      mockSendMessage,
      SESSION_A,
    )
    // Bundle reload preserves the optimistic (typical: bundle has
    // already-persisted messages, optimistic is local-only).
    useChatStore.getState().endReconciliation(SESSION_A, (e) =>
      handleChatEvent(e, mockSendMessage, SESSION_A),
    )
    const messages = useChatStore.getState().messages
    // The optimistic should have been swapped with the real id —
    // exactly one user message remains.
    expect(messages).toHaveLength(1)
    expect(messages[0].id).toBe('real-1')
    expect(messages[0].is_optimistic).toBe(false)
  })
})
