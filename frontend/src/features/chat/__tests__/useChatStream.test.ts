import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'
import { handleChatEvent } from '../useChatStream'
import type { BaseEvent } from '../../../core/types/events'

// Mock the notification store so we can spy on addNotification without
// importing the real Zustand store which may have side-effects.
const mockAddNotification = vi.fn()
vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: {
    getState: () => ({ addNotification: mockAddNotification }),
  },
}))

// Mock sendMessage — we pass it as a parameter but some cases invoke it
// inside action callbacks; we only need to verify it is not called here.
const mockSendMessage = vi.fn()

function makeEvent(overrides: Partial<BaseEvent> & { type: string }): BaseEvent {
  return {
    id: 'evt-1',
    type: overrides.type,
    sequence: 1,
    scope: 'session:s1',
    correlation_id: overrides.correlation_id ?? 'c1',
    timestamp: new Date().toISOString(),
    payload: overrides.payload ?? {},
  } as unknown as BaseEvent
}

describe('useChatStream — CHAT_TOOL_CALL_COMPLETED', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingArtefactRefs: [],
      activeToolCalls: [],
    } as Parameters<typeof useChatStore.setState>[0])
  })

  it('appends artefact_ref to streamingArtefactRefs when present', () => {
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc1',
        tool_name: 'create_artefact',
        success: true,
        artefact_ref: {
          artefact_id: 'a1',
          handle: 'h1',
          title: 't1',
          artefact_type: 'code',
          operation: 'create',
        },
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    expect(useChatStore.getState().streamingArtefactRefs).toHaveLength(1)
    expect(useChatStore.getState().streamingArtefactRefs[0]).toMatchObject({
      artefact_id: 'a1',
      handle: 'h1',
      title: 't1',
    })
  })

  it('does not touch streamingArtefactRefs when artefact_ref is absent', () => {
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc2',
        tool_name: 'web_search',
        success: true,
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    expect(useChatStore.getState().streamingArtefactRefs).toEqual([])
  })
})

describe('useChatStream — CHAT_STREAM_ERROR with refusal', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingRefusalText: null,
    } as Parameters<typeof useChatStore.setState>[0])
  })

  it('sets streamingRefusalText and uses "Request declined" toast title when error_code=refusal', () => {
    const event = makeEvent({
      type: 'chat.stream.error',
      correlation_id: 'c1',
      payload: {
        error_code: 'refusal',
        recoverable: true,
        user_message: 'Model declined your request.',
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    expect(useChatStore.getState().streamingRefusalText).toBe('Model declined your request.')
    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Request declined' }),
    )
  })

  it('uses "Response interrupted" toast title for recoverable non-refusal errors', () => {
    const event = makeEvent({
      type: 'chat.stream.error',
      correlation_id: 'c1',
      payload: {
        error_code: 'stream_timeout',
        recoverable: true,
        user_message: 'Stream timed out.',
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    expect(useChatStore.getState().streamingRefusalText).toBeNull()
    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Response interrupted' }),
    )
  })

  it('uses "Error" toast title for non-recoverable non-refusal errors', () => {
    const event = makeEvent({
      type: 'chat.stream.error',
      correlation_id: 'c1',
      payload: {
        error_code: 'model_error',
        recoverable: false,
        user_message: 'Something went wrong.',
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    expect(useChatStore.getState().streamingRefusalText).toBeNull()
    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Error' }),
    )
  })
})

describe('useChatStream — CHAT_STREAM_ENDED refusal and artefact persistence', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingContent: '',
      streamingThinking: '',
      streamingWebSearchContext: [],
      streamingKnowledgeContext: [],
      streamingArtefactRefs: [],
      streamingRefusalText: null,
      messages: [],
      activeToolCalls: [],
      contextStatus: 'green',
      contextFillPercentage: 0,
    } as any)
  })

  it('assembles final message with refused status and refusal_text', () => {
    useChatStore.setState({
      streamingContent: '',
      streamingRefusalText: 'declined',
    } as any)
    const event = makeEvent({
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        session_id: 's1',
        message_id: 'm1',
        status: 'refused',
        context_status: 'green',
        context_fill_percentage: 0.1,
      },
    })
    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0].status).toBe('refused')
    expect(messages[0].refusal_text).toBe('declined')
  })

  it('persists content-less refused messages on finish', () => {
    useChatStore.setState({
      streamingContent: '',
      streamingThinking: '',
      streamingRefusalText: 'declined',
    } as any)
    const event = makeEvent({
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        session_id: 's1',
        message_id: 'm1',
        status: 'refused',
        context_status: 'green',
        context_fill_percentage: 0,
      },
    })
    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')
    expect(useChatStore.getState().messages).toHaveLength(1)
  })

  it('attaches streamingArtefactRefs to the final message', () => {
    useChatStore.setState({
      streamingContent: 'body',
      streamingArtefactRefs: [
        {
          artefact_id: 'a1',
          handle: 'h1',
          title: 't1',
          artefact_type: 'code',
          operation: 'create',
        },
      ],
    } as any)
    const event = makeEvent({
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        session_id: 's1',
        message_id: 'm1',
        status: 'completed',
        context_status: 'green',
        context_fill_percentage: 0,
      },
    })
    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')
    const messages = useChatStore.getState().messages
    expect(messages[0].artefact_refs).toHaveLength(1)
    expect(messages[0].artefact_refs![0].handle).toBe('h1')
  })
})
