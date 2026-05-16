import { create } from 'zustand'
import type { ChatMessageDto, CompactionCheckpoint, TimelineEntry } from '../api/chat'

type ContextStatus = 'green' | 'yellow' | 'orange' | 'red'

interface ChatError {
  errorCode: string
  recoverable: boolean
  userMessage: string
}

export interface StreamingToolCall {
  toolCallId: string
  toolIndex: number
  toolName: string | null
  argsBuffer: string
  charCount: number
  phase: 'streaming' | 'executing'
  startedAt: number
  parsedArguments: Record<string, unknown> | null
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
  streamingToolCalls: Map<string /* tool_call_id */, StreamingToolCall>
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
  streamingToolCalls: new Map(),
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
   *
   * INVARIANT — unique message id per session: this cache is keyed by
   * message id and `swapMessageId` / `truncateAfter` / `deleteMessage`
   * all assume ids do not collide. When branching ships, the backend
   * MUST guarantee that every message id is unique within the loaded
   * session (e.g. by treating each branch as a separate session, or by
   * minting fresh ids per branch). Reusing an id across branches would
   * silently mix pill caches between divergent histories.
   */
  messagePillContents: Record<string, Map<string, string>>
  contextStatus: ContextStatus
  contextFillPercentage: number
  contextUsedTokens: number
  contextMaxTokens: number
  /**
   * Tokens actually sent upstream on the last completed turn (system prompt
   * + tool definitions + pair-selected history + new user message). May be
   * lower than ``contextUsedTokens`` in long sessions where pair-selection
   * dropped older turns to fit the model's context window. ``null`` when the
   * backend did not supply this number — older events do not carry it.
   */
  contextTokensActuallySent: number | null
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
  /**
   * Append-only history of compact-and-continue snapshots for the active
   * session. Hydrated from ``chatApi.getSession`` on session switch and
   * extended on ``chat.compaction.completed`` WS events. Phase 10 renders
   * each entry as a `compacted` timeline marker between messages.
   */
  compactionCheckpoints: CompactionCheckpoint[]
  /**
   * True while a compaction job is in flight for the active session.
   * Flips to true on ``chat.compaction.started``, back to false on
   * ``chat.compaction.completed`` / ``chat.compaction.failed``. Drives
   * the SparkleCompactButton's loading state and the input-area overlay.
   */
  compactionLoading: boolean
  /**
   * Correlation id of the in-flight compaction request, kept for diagnostic
   * use (matching follow-up progress / completion / failure events to the
   * triggering click). ``null`` whenever ``compactionLoading`` is false.
   */
  compactionCorrelationId: string | null
  /**
   * Correlation ids of compaction requests whose 90 s soft-timeout fired
   * (ChatView.tsx) before the matching ``chat.compaction.completed`` /
   * ``.failed`` arrived. The completion handler consumes this set to
   * suppress the normal success toast — by the time it eventually fires
   * the user has already seen the "running long" notification and a
   * cheerful "Saved Xk tokens" toast on top would be confusing.
   */
  compactionTimedOutCorrelationIds: Set<string>

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
  appendToolCallDelta: (
    toolCallId: string,
    toolIndex: number,
    toolName: string | null,
    argsDelta: string,
    opts: { sessionId: string },
  ) => void
  promoteToolCallToExecuting: (
    toolCallId: string,
    toolName: string,
    parsedArguments: Record<string, unknown>,
    opts: { sessionId: string },
  ) => void
  removeStreamingToolCall: (toolCallId: string, opts: { sessionId: string }) => void
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
  setContextTokensActuallySent: (tokens: number | null) => void
  setReasoningOverride: (override: boolean | null) => void
  setActiveProjectId: (projectId: string | null) => void
  /**
   * Hydrate the active session's compaction checkpoints from the
   * persisted ``ChatSessionDto.compaction_checkpoints`` (or `[]` if the
   * field is absent on legacy sessions). Wipes any prior checkpoints in
   * the store — call on session-switch only.
   */
  setCompactionCheckpoints: (checkpoints: CompactionCheckpoint[]) => void
  /**
   * Append a checkpoint received from a ``chat.compaction.completed``
   * event. The ``sessionId`` guard prevents stale events from a previously
   * active session from polluting the current session's checkpoint list.
   */
  appendCompactionCheckpoint: (sessionId: string, checkpoint: CompactionCheckpoint) => void
  setCompactionLoading: (loading: boolean, correlationId?: string | null) => void
  /**
   * Mark a compaction correlation id as having had its 90 s soft-timeout
   * fire. The completion handler consumes the entry via
   * ``consumeCompactionTimedOut`` to decide whether to suppress the
   * regular success toast.
   */
  markCompactionTimedOut: (correlationId: string) => void
  /**
   * Test-and-clear: returns ``true`` if the correlation id was previously
   * flagged via ``markCompactionTimedOut`` and removes the entry. Returns
   * ``false`` (and is a no-op) otherwise.
   */
  consumeCompactionTimedOut: (correlationId: string) => boolean
  reset: (sessionId?: string) => void
}

const INITIAL_NON_STREAMING = {
  messages: [] as ChatMessageDto[],
  messagePillContents: {} as Record<string, Map<string, string>>,
  contextStatus: 'green' as ContextStatus,
  contextFillPercentage: 0,
  contextUsedTokens: 0,
  contextMaxTokens: 0,
  contextTokensActuallySent: null as number | null,
  error: null as ChatError | null,
  sessionTitle: null as string | null,
  toolsEnabled: false,
  autoRead: false,
  reasoningOverride: null as boolean | null,
  activeProjectId: null as string | null,
  activeSessionId: null as string | null,
  compactionCheckpoints: [] as CompactionCheckpoint[],
  compactionLoading: false,
  compactionCorrelationId: null as string | null,
  compactionTimedOutCorrelationIds: new Set<string>(),
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

  appendToolCallDelta: (toolCallId, toolIndex, toolName, argsDelta, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      const existing = prev.streamingToolCalls.get(toolCallId)
      const next: StreamingToolCall = existing
        ? {
            ...existing,
            toolName: existing.toolName ?? toolName,
            argsBuffer: existing.argsBuffer + argsDelta,
            charCount: existing.charCount + argsDelta.length,
          }
        : {
            toolCallId,
            toolIndex,
            toolName,
            argsBuffer: argsDelta,
            charCount: argsDelta.length,
            phase: 'streaming',
            startedAt: performance.now(),
            parsedArguments: null,
          }
      const nextMap = new Map(prev.streamingToolCalls)
      nextMap.set(toolCallId, next)
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingToolCalls: nextMap,
        }),
      }
    }),

  promoteToolCallToExecuting: (toolCallId, toolName, parsedArguments, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      const existing = prev.streamingToolCalls.get(toolCallId)
      const next: StreamingToolCall = existing
        ? { ...existing, phase: 'executing', toolName, parsedArguments }
        : {
            toolCallId,
            toolIndex: 0,
            toolName,
            argsBuffer: '',
            charCount: 0,
            phase: 'executing',
            startedAt: performance.now(),
            parsedArguments,
          }
      const nextMap = new Map(prev.streamingToolCalls)
      nextMap.set(toolCallId, next)
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingToolCalls: nextMap,
        }),
      }
    }),

  removeStreamingToolCall: (toolCallId, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      if (!prev.streamingToolCalls.has(toolCallId)) return s
      const nextMap = new Map(prev.streamingToolCalls)
      nextMap.delete(toolCallId)
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingToolCalls: nextMap,
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
  setContextTokensActuallySent: (tokens) => set({ contextTokensActuallySent: tokens }),
  setReasoningOverride: (override) => set({ reasoningOverride: override }),
  setActiveProjectId: (projectId) => set({ activeProjectId: projectId }),

  setCompactionCheckpoints: (checkpoints) =>
    set({ compactionCheckpoints: checkpoints }),
  appendCompactionCheckpoint: (sessionId, checkpoint) =>
    set((s) => {
      // Guard against stale events from a previously active session that
      // arrive after the user has navigated away. The caller (useChatStream)
      // already filters by ``event.session_id === sessionId`` before
      // dispatching, so we only need to skip when the user has navigated
      // to a DIFFERENT session in the meantime. A null activeSessionId
      // is benign — the user is mid-load and will receive a fresh hydrate.
      if (s.activeSessionId !== null && s.activeSessionId !== sessionId) {
        return s
      }
      // Idempotency: ignore duplicate checkpoints that arrive twice (e.g.
      // catch-up replay after reconnect).
      if (s.compactionCheckpoints.some((cp) => cp.id === checkpoint.id)) {
        return s
      }
      return { compactionCheckpoints: [...s.compactionCheckpoints, checkpoint] }
    }),
  setCompactionLoading: (loading, correlationId) =>
    set({
      compactionLoading: loading,
      compactionCorrelationId: loading ? (correlationId ?? null) : null,
    }),
  markCompactionTimedOut: (correlationId) =>
    set((s) => {
      if (s.compactionTimedOutCorrelationIds.has(correlationId)) return s
      const next = new Set(s.compactionTimedOutCorrelationIds)
      next.add(correlationId)
      return { compactionTimedOutCorrelationIds: next }
    }),
  consumeCompactionTimedOut: (correlationId) => {
    const cur = useChatStore.getState().compactionTimedOutCorrelationIds
    if (!cur.has(correlationId)) return false
    const next = new Set(cur)
    next.delete(correlationId)
    set({ compactionTimedOutCorrelationIds: next })
    return true
  },

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
