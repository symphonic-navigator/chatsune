import { create } from 'zustand'
import type { ArtefactRef, ChatMessageDto, KnowledgeContextItem, WebSearchContextItem } from '../api/chat'

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
  isWaitingForResponse: boolean
  isStreaming: boolean
  correlationId: string | null
  streamingContent: string
  streamingThinking: string
  streamingWebSearchContext: WebSearchContextItem[]
  streamingKnowledgeContext: KnowledgeContextItem[]
  streamingArtefactRefs: ArtefactRef[]
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
  setStreamingWebSearchContext: (items: WebSearchContextItem[]) => void
  setStreamingKnowledgeContext: (items: KnowledgeContextItem[]) => void
  appendArtefactRef: (ref: ArtefactRef) => void
  setStreamingRefusalText: (text: string | null) => void
  addToolCall: (tc: ActiveToolCall) => void
  completeToolCall: (toolCallId: string) => void
  upsertVisionDescription: (correlationId: string, payload: LiveVisionDescription) => void
  finishStreaming: (finalMessage: ChatMessageDto, contextStatus: ContextStatus, fillPercentage: number, usedTokens?: number, maxTokens?: number) => void
  cancelStreaming: () => void
  truncateAfter: (messageId: string) => void
  updateMessage: (messageId: string, content: string, tokenCount: number) => void
  swapMessageId: (clientId: string, realId: string) => void
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
  isWaitingForResponse: false,
  isStreaming: false,
  correlationId: null as string | null,
  streamingContent: '',
  streamingThinking: '',
  streamingWebSearchContext: [] as WebSearchContextItem[],
  streamingKnowledgeContext: [] as KnowledgeContextItem[],
  streamingArtefactRefs: [] as ArtefactRef[],
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
      streamingWebSearchContext: [], streamingKnowledgeContext: [], activeToolCalls: [], visionDescriptions: {}, error: null,
      streamingArtefactRefs: [], streamingRefusalText: null,
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
  setStreamingWebSearchContext: (items) =>
    set({ streamingWebSearchContext: items }),
  setStreamingKnowledgeContext: (items) =>
    set({ streamingKnowledgeContext: items }),
  appendArtefactRef: (ref) =>
    set((s) => ({ streamingArtefactRefs: [...s.streamingArtefactRefs, ref] })),
  setStreamingRefusalText: (text) =>
    set({ streamingRefusalText: text }),
  addToolCall: (tc) =>
    set((s) => ({ activeToolCalls: [...s.activeToolCalls, tc] })),
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
  finishStreaming: (finalMessage, contextStatus, fillPercentage, usedTokens = 0, maxTokens = 0) =>
    set((s) => ({
      isWaitingForResponse: false, isStreaming: false, correlationId: null,
      streamingContent: '', streamingThinking: '',
      streamingWebSearchContext: [], streamingKnowledgeContext: [], activeToolCalls: [],
      streamingArtefactRefs: [], streamingRefusalText: null,
      streamingSlow: false,
      messages: [...s.messages, finalMessage], contextStatus, contextFillPercentage: fillPercentage,
      contextUsedTokens: usedTokens, contextMaxTokens: maxTokens,
    })),
  cancelStreaming: () =>
    set({
      isWaitingForResponse: false, isStreaming: false, correlationId: null,
      streamingContent: '', streamingThinking: '',
      streamingWebSearchContext: [], streamingKnowledgeContext: [], activeToolCalls: [],
      streamingArtefactRefs: [], streamingRefusalText: null,
      streamingSlow: false,
    }),
  truncateAfter: (messageId) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId)
      if (idx === -1) return s
      return { messages: s.messages.slice(0, idx + 1) }
    }),
  updateMessage: (messageId, content, tokenCount) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, content, token_count: tokenCount } : m,
      ),
    })),
  swapMessageId: (clientId, realId) =>
    set((s) => ({
      messages: s.messages.map((m) => m.id === clientId ? { ...m, id: realId } : m),
    })),
  deleteMessage: (messageId) =>
    set((s) => ({ messages: s.messages.filter((m) => m.id !== messageId) })),
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
