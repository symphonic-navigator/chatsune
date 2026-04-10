import { create } from 'zustand'
import type { ChatMessageDto, WebSearchContextItem } from '../api/chat'
import type { RetrievedChunkDto } from '../types/knowledge'

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
  streamingKnowledgeContext: RetrievedChunkDto[]
  activeToolCalls: ActiveToolCall[]
  visionDescriptions: Record<string, LiveVisionDescription>
  contextStatus: ContextStatus
  contextFillPercentage: number
  error: ChatError | null
  streamingSlow: boolean
  sessionTitle: string | null
  disabledToolGroups: string[]
  reasoningOverride: boolean | null
  setMessages: (messages: ChatMessageDto[]) => void
  appendMessage: (message: ChatMessageDto) => void
  setWaitingForResponse: (waiting: boolean) => void
  startStreaming: (correlationId: string) => void
  appendStreamingContent: (delta: string) => void
  appendStreamingThinking: (delta: string) => void
  setStreamingWebSearchContext: (items: WebSearchContextItem[]) => void
  setStreamingKnowledgeContext: (items: RetrievedChunkDto[]) => void
  addToolCall: (tc: ActiveToolCall) => void
  completeToolCall: (toolCallId: string) => void
  upsertVisionDescription: (correlationId: string, payload: LiveVisionDescription) => void
  finishStreaming: (finalMessage: ChatMessageDto, contextStatus: ContextStatus, fillPercentage: number) => void
  cancelStreaming: () => void
  truncateAfter: (messageId: string) => void
  updateMessage: (messageId: string, content: string, tokenCount: number) => void
  swapMessageId: (clientId: string, realId: string) => void
  deleteMessage: (messageId: string) => void
  setError: (error: ChatError) => void
  clearError: () => void
  setStreamingSlow: (slow: boolean) => void
  setSessionTitle: (title: string | null) => void
  setDisabledToolGroups: (groups: string[]) => void
  setContextStatus: (status: ContextStatus) => void
  setContextFillPercentage: (percentage: number) => void
  setReasoningOverride: (override: boolean | null) => void
  waitingForLock: { providerId: string; holderSource: string } | null
  setWaitingForLock: (info: { providerId: string; holderSource: string }) => void
  clearWaitingForLock: () => void
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
  streamingKnowledgeContext: [] as RetrievedChunkDto[],
  activeToolCalls: [] as ActiveToolCall[],
  visionDescriptions: {} as Record<string, LiveVisionDescription>,
  contextStatus: 'green' as ContextStatus,
  contextFillPercentage: 0,
  error: null as ChatError | null,
  streamingSlow: false,
  sessionTitle: null as string | null,
  disabledToolGroups: [] as string[],
  reasoningOverride: null as boolean | null,
  waitingForLock: null as { providerId: string; holderSource: string } | null,
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
      streamingSlow: false,
    }),
  appendStreamingContent: (delta) =>
    set((s) => ({ streamingContent: s.streamingContent + delta, streamingSlow: false })),
  appendStreamingThinking: (delta) =>
    set((s) => ({ streamingThinking: s.streamingThinking + delta, streamingSlow: false })),
  setStreamingWebSearchContext: (items) =>
    set({ streamingWebSearchContext: items }),
  setStreamingKnowledgeContext: (items) =>
    set({ streamingKnowledgeContext: items }),
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
  finishStreaming: (finalMessage, contextStatus, fillPercentage) =>
    set((s) => ({
      isWaitingForResponse: false, isStreaming: false, correlationId: null,
      streamingContent: '', streamingThinking: '',
      streamingWebSearchContext: [], streamingKnowledgeContext: [], activeToolCalls: [],
      streamingSlow: false,
      messages: [...s.messages, finalMessage], contextStatus, contextFillPercentage: fillPercentage,
    })),
  cancelStreaming: () =>
    set({
      isWaitingForResponse: false, isStreaming: false, correlationId: null,
      streamingContent: '', streamingThinking: '',
      streamingWebSearchContext: [], streamingKnowledgeContext: [], activeToolCalls: [],
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
  setDisabledToolGroups: (groups) => set({ disabledToolGroups: groups }),
  setContextStatus: (status) => set({ contextStatus: status }),
  setContextFillPercentage: (percentage) => set({ contextFillPercentage: percentage }),
  setReasoningOverride: (override) => set({ reasoningOverride: override }),
  setWaitingForLock: (info) => set({ waitingForLock: info }),
  clearWaitingForLock: () => set({ waitingForLock: null }),
  reset: (sessionId) => set({ ...INITIAL_STATE, activeSessionId: sessionId ?? null }),
}))
