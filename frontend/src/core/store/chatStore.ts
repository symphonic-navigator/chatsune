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

interface ChatState {
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
  contextStatus: ContextStatus
  contextFillPercentage: number
  contextUsedTokens: number
  contextMaxTokens: number
  error: ChatError | null
  streamingSlow: boolean
  sessionTitle: string | null
  toolsEnabled: boolean
  autoRead: boolean
  reasoningOverride: boolean | null
  setMessages: (messages: ChatMessageDto[]) => void
  appendMessage: (message: ChatMessageDto) => void
  setWaitingForResponse: (waiting: boolean) => void
  startStreaming: (correlationId: string) => void
  appendStreamingContent: (delta: string) => void
  replaceInStreamingContent: (search: string, replacement: string) => void
  appendStreamingThinking: (delta: string) => void
  /**
   * Append a timeline entry to the active stream. The store assigns the
   * `seq` automatically (monotonic per stream); any `seq` on the supplied
   * entry is ignored. This frees the two hooks that produce timeline entries
   * (`useChatStream`, `useKnowledgeEvents`) from having to share a counter.
   */
  appendStreamingEvent: (entry: TimelineEntry) => void
  setStreamingRefusalText: (text: string | null) => void
  addToolCall: (tc: ActiveToolCall) => void
  completeToolCall: (toolCallId: string) => void
  upsertVisionDescription: (correlationId: string, payload: LiveVisionDescription) => void
  finishStreaming: (
    finalMessage: ChatMessageDto,
    contextStatus: ContextStatus,
    fillPercentage: number,
    usedTokens?: number,
    maxTokens?: number,
    pillContents?: Map<string, string>,
  ) => void
  cancelStreaming: () => void
  truncateAfter: (messageId: string) => void
  updateMessage: (messageId: string, content: string, tokenCount: number) => void
  swapMessageId: (clientId: string, realId: string, patch?: Partial<ChatMessageDto>) => void
  deleteMessage: (messageId: string) => void
  setError: (error: ChatError) => void
  clearError: () => void
  setStreamingSlow: (slow: boolean) => void
  setSessionTitle: (title: string | null) => void
  setToolsEnabled: (value: boolean) => void
  setAutoRead: (value: boolean) => void
  setContextStatus: (status: ContextStatus) => void
  setContextFillPercentage: (percentage: number) => void
  setContextTokens: (used: number, max: number) => void
  setReasoningOverride: (override: boolean | null) => void
  activeSessionId: string | null
  reset: (sessionId?: string) => void
}

const INITIAL_STATE = {
  messages: [] as ChatMessageDto[],
  messagePillContents: {} as Record<string, Map<string, string>>,
  isWaitingForResponse: false,
  isStreaming: false,
  correlationId: null as string | null,
  streamingContent: '',
  streamingThinking: '',
  streamingEvents: [] as TimelineEntry[],
  streamingRefusalText: null as string | null,
  activeToolCalls: [] as ActiveToolCall[],
  visionDescriptions: {} as Record<string, LiveVisionDescription>,
  contextStatus: 'green' as ContextStatus,
  contextFillPercentage: 0,
  contextUsedTokens: 0,
  contextMaxTokens: 0,
  error: null as ChatError | null,
  streamingSlow: false,
  sessionTitle: null as string | null,
  toolsEnabled: false,
  autoRead: false,
  reasoningOverride: null as boolean | null,
  activeSessionId: null as string | null,
}

export const useChatStore = create<ChatState>((set, _get) => ({
  ...INITIAL_STATE,

  setMessages: (messages) => set({ messages }),
  appendMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),
  setWaitingForResponse: (waiting) => set({ isWaitingForResponse: waiting }),
  startStreaming: (correlationId) =>
    set({
      isWaitingForResponse: false, isStreaming: true, correlationId,
      streamingContent: '', streamingThinking: '',
      streamingEvents: [], activeToolCalls: [], visionDescriptions: {}, error: null,
      streamingRefusalText: null,
      streamingSlow: false,
    }),
  appendStreamingContent: (delta) =>
    set((s) => ({ streamingContent: s.streamingContent + delta, streamingSlow: false })),
  replaceInStreamingContent: (search, replacement) =>
    set((s) => ({
      streamingContent: s.streamingContent.replace(search, replacement),
    })),
  appendStreamingThinking: (delta) =>
    set((s) => ({ streamingThinking: s.streamingThinking + delta, streamingSlow: false })),
  appendStreamingEvent: (entry) =>
    set((s) => {
      const seq = s.streamingEvents.length
      const next = { ...entry, seq } as TimelineEntry
      return { streamingEvents: [...s.streamingEvents, next] }
    }),
  setStreamingRefusalText: (text) =>
    set({ streamingRefusalText: text }),
  addToolCall: (tc) =>
    // Idempotent on tool_call_id: some upstream providers (notably
    // DeepSeek via OpenRouter) emit two finish_reason="tool_calls"
    // chunks for the same call, which used to surface as a duplicated
    // ToolCallStarted event and a React duplicate-key warning. Replace
    // an existing entry with the same id instead of appending.
    set((s) => {
      const idx = s.activeToolCalls.findIndex((x) => x.id === tc.id)
      if (idx >= 0) {
        const next = [...s.activeToolCalls]
        next[idx] = tc
        return { activeToolCalls: next }
      }
      return { activeToolCalls: [...s.activeToolCalls, tc] }
    }),
  completeToolCall: (toolCallId) =>
    set((s) => ({
      activeToolCalls: s.activeToolCalls.map((tc) =>
        tc.id === toolCallId ? { ...tc, status: 'done' as const } : tc,
      ),
    })),
  upsertVisionDescription: (correlationId, payload) =>
    set((s) => ({
      visionDescriptions: {
        ...s.visionDescriptions,
        [`${correlationId}:${payload.file_id}`]: payload,
      },
    })),
  finishStreaming: (finalMessage, contextStatus, fillPercentage, usedTokens = 0, maxTokens = 0, pillContents) =>
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
      return {
        isWaitingForResponse: false, isStreaming: false, correlationId: null,
        streamingContent: '', streamingThinking: '',
        streamingEvents: [], activeToolCalls: [],
        streamingRefusalText: null,
        streamingSlow: false,
        messages: [...s.messages, finalMessage], contextStatus, contextFillPercentage: fillPercentage,
        contextUsedTokens: usedTokens, contextMaxTokens: maxTokens,
        messagePillContents: nextPillCache,
      }
    }),
  cancelStreaming: () =>
    set({
      isWaitingForResponse: false, isStreaming: false, correlationId: null,
      streamingContent: '', streamingThinking: '',
      streamingEvents: [], activeToolCalls: [],
      streamingRefusalText: null,
      streamingSlow: false,
    }),
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
  setStreamingSlow: (slow) => set({ streamingSlow: slow }),
  setSessionTitle: (title) => set({ sessionTitle: title }),
  setToolsEnabled: (value) => set({ toolsEnabled: value }),
  setAutoRead: (value) => set({ autoRead: value }),
  setContextStatus: (status) => set({ contextStatus: status }),
  setContextFillPercentage: (percentage) => set({ contextFillPercentage: percentage }),
  setContextTokens: (used, max) => set({ contextUsedTokens: used, contextMaxTokens: max }),
  setReasoningOverride: (override) => set({ reasoningOverride: override }),
  reset: (sessionId) => set({ ...INITIAL_STATE, activeSessionId: sessionId ?? null }),
}))
