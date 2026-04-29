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

type StoreState = ReturnType<typeof useChatStore.getState>

describe('useChatStream — CHAT_TOOL_CALL_COMPLETED', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingEvents: [],
      activeToolCalls: [],
    } as Partial<StoreState> as StoreState)
  })

  it('appends an artefact timeline entry when artefact_ref is present', () => {
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

    const events = useChatStore.getState().streamingEvents
    expect(events).toHaveLength(1)
    expect(events[0].kind).toBe('artefact')
    if (events[0].kind === 'artefact') {
      expect(events[0].ref).toMatchObject({ handle: 'h1', title: 't1' })
    }
  })

  it('does not append a timeline entry for known-context tools (web_search)', () => {
    // CHAT_WEB_SEARCH_CONTEXT carries the web-search results separately;
    // the tool_call.completed event for web_search is therefore a no-op
    // for the timeline.
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

    expect(useChatStore.getState().streamingEvents).toEqual([])
  })

  it('appends an image entry for generate_image with refs', () => {
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc3',
        tool_name: 'generate_image',
        success: true,
        moderated_count: 1,
        image_refs: [
          {
            id: 'i1', blob_url: '/b/1', thumb_url: '/t/1', width: 512, height: 512,
            prompt: 'a cat', model_id: 'm', tool_call_id: 'tc3',
          },
        ],
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    const events = useChatStore.getState().streamingEvents
    expect(events).toHaveLength(1)
    expect(events[0].kind).toBe('image')
    if (events[0].kind === 'image') {
      expect(events[0].refs).toHaveLength(1)
      expect(events[0].moderated_count).toBe(1)
    }
  })

  it('appends a tool_call entry when knowledge_search fails (must not silently swallow)', () => {
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc-kf',
        tool_name: 'knowledge_search',
        arguments: { query: 'x' },
        success: false,
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    const events = useChatStore.getState().streamingEvents
    expect(events).toHaveLength(1)
    expect(events[0].kind).toBe('tool_call')
    if (events[0].kind === 'tool_call') {
      expect(events[0].tool_name).toBe('knowledge_search')
      expect(events[0].success).toBe(false)
    }
  })

  it('appends a tool_call entry when web_search fails', () => {
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc-wf',
        tool_name: 'web_search',
        arguments: { query: 'x' },
        success: false,
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    const events = useChatStore.getState().streamingEvents
    expect(events).toHaveLength(1)
    expect(events[0].kind).toBe('tool_call')
    if (events[0].kind === 'tool_call') {
      expect(events[0].tool_name).toBe('web_search')
      expect(events[0].success).toBe(false)
    }
  })

  it('appends a generic tool_call entry for arbitrary tools', () => {
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc4',
        tool_name: 'custom_thing',
        arguments: { q: 'x' },
        success: false,
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    const events = useChatStore.getState().streamingEvents
    expect(events).toHaveLength(1)
    expect(events[0].kind).toBe('tool_call')
    if (events[0].kind === 'tool_call') {
      expect(events[0].tool_name).toBe('custom_thing')
      expect(events[0].success).toBe(false)
    }
  })
})

describe('useChatStream — CHAT_WEB_SEARCH_CONTEXT', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingEvents: [],
      activeToolCalls: [],
    } as Partial<StoreState> as StoreState)
  })

  it('appends a web_search timeline entry', () => {
    const event = makeEvent({
      type: 'chat.web_search.context',
      correlation_id: 'c1',
      payload: {
        items: [
          { title: 't1', url: 'https://x', snippet: 's1', source_type: 'search' },
        ],
      },
    })

    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')

    const events = useChatStore.getState().streamingEvents
    expect(events).toHaveLength(1)
    expect(events[0].kind).toBe('web_search')
    if (events[0].kind === 'web_search') {
      expect(events[0].items).toHaveLength(1)
      expect(events[0].items[0].url).toBe('https://x')
    }
  })
})

describe('useChatStream — CHAT_STREAM_ERROR with refusal', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingRefusalText: null,
    } as Partial<StoreState> as StoreState)
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

describe('useChatStream — CHAT_STREAM_ENDED refusal and event persistence', () => {
  beforeEach(() => {
    mockAddNotification.mockReset()
    mockSendMessage.mockReset()
    useChatStore.setState({
      correlationId: 'c1',
      streamingContent: '',
      streamingThinking: '',
      streamingEvents: [],
      streamingRefusalText: null,
      messages: [],
      activeToolCalls: [],
      contextStatus: 'green',
      contextFillPercentage: 0,
    } as Partial<StoreState> as StoreState)
  })

  it('assembles final message with refused status and refusal_text', () => {
    useChatStore.setState({
      streamingContent: '',
      streamingRefusalText: 'declined',
    } as Partial<StoreState> as StoreState)
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
    } as Partial<StoreState> as StoreState)
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

  it('uses persisted events from stream-ended payload when present', () => {
    useChatStore.setState({
      streamingContent: 'body',
      streamingEvents: [
        {
          kind: 'web_search',
          seq: 0,
          items: [{ title: 'live', url: 'u', snippet: 's' }],
        },
      ],
    } as Partial<StoreState> as StoreState)
    const event = makeEvent({
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        session_id: 's1',
        message_id: 'm1',
        status: 'completed',
        context_status: 'green',
        context_fill_percentage: 0,
        events: [
          {
            kind: 'artefact',
            seq: 0,
            ref: {
              artefact_id: 'a1', handle: 'h1', title: 't1',
              artefact_type: 'code', operation: 'create',
            },
          },
        ],
      },
    })
    handleChatEvent(event, mockSendMessage as typeof import('../../../core/websocket/connection').sendMessage, 's1')
    const messages = useChatStore.getState().messages
    expect(messages[0].events).toHaveLength(1)
    expect(messages[0].events![0].kind).toBe('artefact')
  })

  it('falls back to streamingEvents when payload omits events (BE rollout lag)', () => {
    useChatStore.setState({
      streamingContent: 'body',
      streamingEvents: [
        {
          kind: 'artefact',
          seq: 0,
          ref: {
            artefact_id: 'a1', handle: 'h1', title: 't1',
            artefact_type: 'code', operation: 'create',
          },
        },
      ],
    } as Partial<StoreState> as StoreState)
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
    expect(messages[0].events).toHaveLength(1)
    expect(messages[0].events![0].kind).toBe('artefact')
  })
})
