import { create } from 'zustand'
import type { ChatMessageDto, TimelineEntry } from '../api/chat'

type ContextStatus = 'green' | 'yellow' | 'orange' | 'red'

interface ChatError {
  errorCode: string
  recoverable: boolean
  userMessage: string
}

interface ActiveToolCall {
  id: string
  toolName: string
  arguments: Record<string, unknown>
  status: 'running' | 'done'
}

export interface LiveVisionDescription {
  file_id: string
  display_name: string
  model_id: string
  status: 'pending' | 'success' | 'error'
  text: string | null
  error: string | null
}

/**
 * Per-session streaming state. Multiple sessions may stream concurrently
 * (background completions), so each session owns its own slot in
 * `streamsBySession`. Reads via `getStreamFor(sessionId)`; writes via the
 * streaming actions, all of which take an explicit `{ sessionId }` opt
 * because the caller may need to write into a non-active stream.
 */
export interface SessionStreamingState {
  isWaitingForResponse: boolean
  isStreaming: boolean
  correlationId: string | null
  streamingContent: string
  streamingThinking: string
  /**
   * Chronological timeline of tool-derived events for the in-flight assistant
   * message. The store assigns a monotonic `seq` to every entry it appends,
   * scoped per stream — callers do not coordinate seq numbers themselves.
   */
  streamingEvents: TimelineEntry[]
  streamingRefusalText: string | null
  activeToolCalls: ActiveToolCall[]
  visionDescriptions: Record<string, LiveVisionDescription>
  streamingSlow: boolean
}

const EMPTY_STREAM: SessionStreamingState = {
  isWaitingForResponse: false,
  isStreaming: false,
  correlationId: null,
  streamingContent: '',
  streamingThinking: '',
  streamingEvents: [],
  streamingRefusalText: null,
  activeToolCalls: [],
  visionDescriptions: {},
  streamingSlow: false,
}

interface ChatState {
  // Per-session streaming slots — survive across activeSessionId changes.
  streamsBySession: Map<string, SessionStreamingState>

  // Session-load state (these still swap on session switch).
  messages: ChatMessageDto[]
  /**
   * Cache of inline-trigger pill contents (effectId → pillContent) per
   * persisted message id. Populated by `finishStreaming` from the active
   * Group's `renderedPillsMap`. Read by `AssistantMessage` to render
   * pills for messages that just finished streaming, where the persisted
   * `content` field already contains placeholders (no raw tags) and the
   * persisted-render buffer would otherwise produce an empty map.
   *
   * F5 / history-load do NOT populate this — the on-disk message has raw
   * tags so the persisted-render path reconstructs the map by re-parsing.
   */
  messagePillContents: Record<string, Map<string, string>>
  contextStatus: ContextStatus
  contextFillPercentage: number
  contextUsedTokens: number
  contextMaxTokens: number
  error: ChatError | null
  sessionTitle: string | null
  toolsEnabled: boolean
  autoRead: boolean
  reasoningOverride: boolean | null
  /**
   * The ``project_id`` of the currently-loaded chat session, mirrored
   * here so the in-chat ProjectSwitcher in the Topbar can render
   * reliably even when ``useChatSessions`` does not include
   * project-bound chats. Hydrated from ``chatApi.getSession`` in
   * ChatView and kept in sync via ``CHAT_SESSION_PROJECT_UPDATED``.
   */
  activeProjectId: string | null
  activeSessionId: string | null

  // Read accessors
  getStreamFor: (sessionId: string) => SessionStreamingState | null

  // Streaming actions — every action takes an explicit { sessionId }
  // since callers may write into a stream that is not the active one.
  setMessages: (messages: ChatMessageDto[]) => void
  appendMessage: (message: ChatMessageDto) => void
  setWaitingForResponse: (waiting: boolean, opts: { sessionId: string }) => void
  startStreaming: (correlationId: string, opts: { sessionId: string }) => void
  appendStreamingContent: (delta: string, opts: { sessionId: string }) => void
  replaceInStreamingContent: (
    search: string,
    replacement: string,
    opts: { sessionId: string },
  ) => void
  appendStreamingThinking: (delta: string, opts: { sessionId: string }) => void
  /**
   * Append a timeline entry to the active stream. The store assigns the
   * `seq` automatically (monotonic per stream); any `seq` on the supplied
   * entry is ignored. This frees the two hooks that produce timeline entries
   * (`useChatStream`, `useKnowledgeEvents`) from having to share a counter.
   */
  appendStreamingEvent: (entry: TimelineEntry, opts: { sessionId: string }) => void
  setStreamingRefusalText: (text: string | null, opts: { sessionId: string }) => void
  addToolCall: (tc: ActiveToolCall, opts: { sessionId: string }) => void
  completeToolCall: (toolCallId: string, opts: { sessionId: string }) => void
  upsertVisionDescription: (
    correlationId: string,
    payload: LiveVisionDescription,
    opts: { sessionId: string },
  ) => void
  finishStreaming: (
    finalMessage: ChatMessageDto,
    contextStatus: ContextStatus,
    fillPercentage: number,
    usedTokens: number,
    maxTokens: number,
    pillContents: Map<string, string> | undefined,
    opts: { sessionId: string },
  ) => void
  cancelStreaming: (opts: { sessionId: string }) => void
  setStreamingSlow: (slow: boolean, opts: { sessionId: string }) => void

  // Non-streaming actions — unchanged
  truncateAfter: (messageId: string) => void
  updateMessage: (messageId: string, content: string, tokenCount: number) => void
  swapMessageId: (clientId: string, realId: string, patch?: Partial<ChatMessageDto>) => void
  deleteMessage: (messageId: string) => void
  setError: (error: ChatError) => void
  clearError: () => void
  setSessionTitle: (title: string | null) => void
  setToolsEnabled: (value: boolean) => void
  setAutoRead: (value: boolean) => void
  setContextStatus: (status: ContextStatus) => void
  setContextFillPercentage: (percentage: number) => void
  setContextTokens: (used: number, max: number) => void
  setReasoningOverride: (override: boolean | null) => void
  setActiveProjectId: (projectId: string | null) => void
  reset: (sessionId?: string) => void
}

const INITIAL_NON_STREAMING = {
  messages: [] as ChatMessageDto[],
  messagePillContents: {} as Record<string, Map<string, string>>,
  contextStatus: 'green' as ContextStatus,
  contextFillPercentage: 0,
  contextUsedTokens: 0,
  contextMaxTokens: 0,
  error: null as ChatError | null,
  sessionTitle: null as string | null,
  toolsEnabled: false,
  autoRead: false,
  reasoningOverride: null as boolean | null,
  activeProjectId: null as string | null,
  activeSessionId: null as string | null,
}

function withStream(
  m: Map<string, SessionStreamingState>,
  sessionId: string,
  patch: Partial<SessionStreamingState>,
): Map<string, SessionStreamingState> {
  const next = new Map(m)
  const prev = next.get(sessionId) ?? EMPTY_STREAM
  next.set(sessionId, { ...prev, ...patch })
  return next
}

function clearStream(
  m: Map<string, SessionStreamingState>,
  sessionId: string,
): Map<string, SessionStreamingState> {
  if (!m.has(sessionId)) return m
  const next = new Map(m)
  next.delete(sessionId)
  return next
}

export const useChatStore = create<ChatState>((set, get) => ({
  streamsBySession: new Map(),
  ...INITIAL_NON_STREAMING,

  getStreamFor: (sessionId) => get().streamsBySession.get(sessionId) ?? null,

  setMessages: (messages) => set({ messages }),
  appendMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),

  setWaitingForResponse: (waiting, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        isWaitingForResponse: waiting,
      }),
    })),

  startStreaming: (correlationId, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        ...EMPTY_STREAM,
        isStreaming: true,
        correlationId,
      }),
    })),

  appendStreamingContent: (delta, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingContent: prev.streamingContent + delta,
          streamingSlow: false,
        }),
      }
    }),

  replaceInStreamingContent: (search, replacement, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingContent: prev.streamingContent.replace(search, replacement),
        }),
      }
    }),

  appendStreamingThinking: (delta, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingThinking: prev.streamingThinking + delta,
          streamingSlow: false,
        }),
      }
    }),

  appendStreamingEvent: (entry, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      const seq = prev.streamingEvents.length
      const next = { ...entry, seq } as TimelineEntry
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingEvents: [...prev.streamingEvents, next],
        }),
      }
    }),

  setStreamingRefusalText: (text, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingRefusalText: text,
      }),
    })),

  addToolCall: (tc, { sessionId }) =>
    // Idempotent on tool_call_id: some upstream providers (notably
    // DeepSeek via OpenRouter) emit two finish_reason="tool_calls"
    // chunks for the same call, which used to surface as a duplicated
    // ToolCallStarted event and a React duplicate-key warning. Replace
    // an existing entry with the same id instead of appending.
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      const idx = prev.activeToolCalls.findIndex((x) => x.id === tc.id)
      const nextCalls = idx >= 0
        ? prev.activeToolCalls.map((x, i) => (i === idx ? tc : x))
        : [...prev.activeToolCalls, tc]
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          activeToolCalls: nextCalls,
        }),
      }
    }),

  completeToolCall: (toolCallId, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          activeToolCalls: prev.activeToolCalls.map((tc) =>
            tc.id === toolCallId ? { ...tc, status: 'done' as const } : tc,
          ),
        }),
      }
    }),

  upsertVisionDescription: (correlationId, payload, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          visionDescriptions: {
            ...prev.visionDescriptions,
            [`${correlationId}:${payload.file_id}`]: payload,
          },
        }),
      }
    }),

  finishStreaming: (
    finalMessage,
    contextStatus,
    fillPercentage,
    usedTokens = 0,
    maxTokens = 0,
    pillContents,
    { sessionId },
  ) =>
    // The persisted message's `events` is the source of truth at stream end.
    // We discard `streamingEvents` rather than carrying anything across.
    set((s) => {
      // Only cache pill contents when there is at least one inline-trigger
      // entry for this message — keeps the cache lean for plain-text
      // messages and matches the post-stream render path's expectations.
      const nextPillCache =
        pillContents && pillContents.size > 0 && finalMessage.id
          ? { ...s.messagePillContents, [finalMessage.id]: pillContents }
          : s.messagePillContents
      // Only append the message into the visible transcript when the
      // finishing stream belongs to the active session. Background-completion
      // results are loaded from the DB on next session switch.
      const isActive = sessionId === s.activeSessionId
      const messages = isActive ? [...s.messages, finalMessage] : s.messages
      return {
        streamsBySession: clearStream(s.streamsBySession, sessionId),
        messages,
        contextStatus: isActive ? contextStatus : s.contextStatus,
        contextFillPercentage: isActive ? fillPercentage : s.contextFillPercentage,
        contextUsedTokens: isActive ? usedTokens : s.contextUsedTokens,
        contextMaxTokens: isActive ? maxTokens : s.contextMaxTokens,
        messagePillContents: nextPillCache,
      }
    }),

  cancelStreaming: ({ sessionId }) =>
    set((s) => ({ streamsBySession: clearStream(s.streamsBySession, sessionId) })),

  setStreamingSlow: (slow, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingSlow: slow,
      }),
    })),

  truncateAfter: (messageId) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId)
      if (idx === -1) return s
      const nextMessages = s.messages.slice(0, idx + 1)
      const surviving = new Set(nextMessages.map((m) => m.id))
      const nextCache: Record<string, Map<string, string>> = {}
      for (const [k, v] of Object.entries(s.messagePillContents)) {
        if (surviving.has(k)) nextCache[k] = v
      }
      return { messages: nextMessages, messagePillContents: nextCache }
    }),

  updateMessage: (messageId, content, tokenCount) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, content, token_count: tokenCount } : m,
      ),
    })),

  swapMessageId: (clientId, realId, patch) =>
    set((s) => {
      const messages = s.messages.map((m) =>
        m.id === clientId ? { ...m, id: realId, ...(patch ?? {}) } : m,
      )
      let messagePillContents = s.messagePillContents
      if (clientId in messagePillContents) {
        const { [clientId]: cached, ...rest } = messagePillContents
        messagePillContents = { ...rest, [realId]: cached }
      }
      return { messages, messagePillContents }
    }),

  deleteMessage: (messageId) =>
    set((s) => {
      const { [messageId]: _removed, ...nextCache } = s.messagePillContents
      return {
        messages: s.messages.filter((m) => m.id !== messageId),
        messagePillContents: nextCache,
      }
    }),

  setError: (error) => set({ error }),
  clearError: () => set({ error: null }),
  setSessionTitle: (title) => set({ sessionTitle: title }),
  setToolsEnabled: (value) => set({ toolsEnabled: value }),
  setAutoRead: (value) => set({ autoRead: value }),
  setContextStatus: (status) => set({ contextStatus: status }),
  setContextFillPercentage: (percentage) => set({ contextFillPercentage: percentage }),
  setContextTokens: (used, max) => set({ contextUsedTokens: used, contextMaxTokens: max }),
  setReasoningOverride: (override) => set({ reasoningOverride: override }),
  setActiveProjectId: (projectId) => set({ activeProjectId: projectId }),

  // reset(sessionId) — switch to a session and reset its non-streaming
  // session-load state. DOES NOT touch streamsBySession: stream slots
  // are owned by the streaming actions (finishStreaming/cancelStreaming),
  // and a session being switched to may have a live background stream
  // whose state must be preserved for seamless resume.
  //
  // reset() with no argument — full reset, including every stream slot
  // (used for logout / app teardown).
  reset: (sessionId) =>
    set((s) => ({
      ...INITIAL_NON_STREAMING,
      streamsBySession: sessionId === undefined ? new Map() : s.streamsBySession,
      activeSessionId: sessionId ?? null,
    })),
}))
