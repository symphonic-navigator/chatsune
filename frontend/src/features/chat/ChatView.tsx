import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { chatApi, type ChatMessageDto } from '../../core/api/chat'
import { llmApi } from '../../core/api/llm'
import { sendMessage } from '../../core/websocket/connection'
import { useChatStore } from '../../core/store/chatStore'
import { useChatStream } from './useChatStream'
import { useAutoScroll } from './useAutoScroll'
import { useHighlighter } from './useMarkdown'
import { MessageList } from './MessageList'
import { ChatInput, type ChatInputHandle } from './ChatInput'
import { ToolToggles } from './ToolToggles'
import { ContextStatusPill } from './ContextStatusPill'
import { useAttachments } from './useAttachments'
import { AttachmentStrip } from './AttachmentStrip'
import { UploadBrowserPanel } from './UploadBrowserPanel'
import { CHAKRA_PALETTE, type ChakraColour } from '../../core/types/chakra'
import type { PersonaDto } from '../../core/types/persona'

interface ChatViewProps {
  persona: PersonaDto | null
}

export function ChatView({ persona }: ChatViewProps) {
  const { personaId, sessionId } = useParams<{ personaId: string; sessionId?: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const chatInputRef = useRef<ChatInputHandle>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [showUploadBrowser, setShowUploadBrowser] = useState(false)
  const [modelSupportsTools, setModelSupportsTools] = useState(true)
  const [modelSupportsReasoning, setModelSupportsReasoning] = useState(true)
  const resolvingSession = useRef(false)

  const isIncognito = searchParams.get('incognito') === '1'
  const incognitoIdRef = useRef(`incognito-${crypto.randomUUID()}`)
  const effectiveSessionId = isIncognito ? incognitoIdRef.current : sessionId

  useEffect(() => {
    resolvingSession.current = false
    if (isIncognito) return
    if (!personaId || sessionId) return
    resolvingSession.current = true

    const forceNew = searchParams.get('new') === '1'

    if (forceNew) {
      chatApi
        .createSession(personaId)
        .then((session) => navigate(`/chat/${personaId}/${session.id}`, { replace: true }))
        .finally(() => { resolvingSession.current = false })
      return
    }

    // Resume latest session, or create a new one if none exists
    chatApi
      .listSessions()
      .then((sessions) => {
        const latest = sessions
          .filter((s) => s.persona_id === personaId)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
        if (latest) {
          navigate(`/chat/${personaId}/${latest.id}`, { replace: true })
        } else {
          return chatApi.createSession(personaId).then((session) => {
            navigate(`/chat/${personaId}/${session.id}`, { replace: true })
          })
        }
      })
      .finally(() => { resolvingSession.current = false })
  }, [searchParams, personaId, sessionId, navigate, isIncognito])

  const messages = useChatStore((s) => s.messages)
  const isWaitingForResponse = useChatStore((s) => s.isWaitingForResponse)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const correlationId = useChatStore((s) => s.correlationId)
  const streamingContent = useChatStore((s) => s.streamingContent)
  const streamingThinking = useChatStore((s) => s.streamingThinking)
  const streamingWebSearchContext = useChatStore((s) => s.streamingWebSearchContext)
  const activeToolCalls = useChatStore((s) => s.activeToolCalls)
  const contextStatus = useChatStore((s) => s.contextStatus)
  const contextFillPercentage = useChatStore((s) => s.contextFillPercentage)
  const error = useChatStore((s) => s.error)
  const sessionTitle = useChatStore((s) => s.sessionTitle)
  const disabledToolGroups = useChatStore((s) => s.disabledToolGroups)
  const reasoningOverride = useChatStore((s) => s.reasoningOverride)

  const personaReasoningDefault = persona?.reasoning_enabled ?? false
  const effectiveReasoning = reasoningOverride !== null ? reasoningOverride : personaReasoningDefault

  const attachments = useAttachments(personaId)
  const highlighter = useHighlighter()
  const { containerRef, showScrollButton, scrollToBottom } = useAutoScroll(isStreaming)

  useChatStream(effectiveSessionId ?? null)

  useEffect(() => {
    const store = useChatStore.getState()
    store.reset()

    if (isIncognito) {
      // Load model capabilities from persona
      if (persona?.model_unique_id) {
        const uid = persona.model_unique_id
        if (uid.includes(':')) {
          const providerId = uid.split(':')[0]
          const modelSlug = uid.split(':').slice(1).join(':')
          llmApi.listModels(providerId)
            .then((models) => {
              const model = models.find((m) => m.model_id === modelSlug)
              setModelSupportsTools(model?.supports_tool_calls ?? false)
              setModelSupportsReasoning(model?.supports_reasoning ?? false)
            })
            .catch(() => {})
        }
      }
      return
    }

    if (!sessionId) return

    setIsLoading(true)
    chatApi
      .getMessages(sessionId)
      .then((msgs: ChatMessageDto[]) => {
        useChatStore.getState().setMessages(msgs)
      })
      .catch(() => {})
      .finally(() => {
        setIsLoading(false)
      })

    chatApi
      .getSession(sessionId)
      .then((session) => {
        useChatStore.getState().setSessionTitle(session.title)
        useChatStore.getState().setDisabledToolGroups(session.disabled_tool_groups ?? [])
        useChatStore.getState().setReasoningOverride(session.reasoning_override ?? null)

        // Check if the model supports tool calls
        const uid = session.model_unique_id
        if (uid && uid.includes(':')) {
          const providerId = uid.split(':')[0]
          const modelSlug = uid.split(':').slice(1).join(':')
          llmApi.listModels(providerId)
            .then((models) => {
              const model = models.find((m) => m.model_id === modelSlug)
              setModelSupportsTools(model?.supports_tool_calls ?? false)
              setModelSupportsReasoning(model?.supports_reasoning ?? false)
            })
            .catch(() => setModelSupportsTools(true))
        }
      })
      .catch(() => {})
  }, [sessionId, scrollToBottom, isIncognito, persona])

  // Shift+Esc focuses the input
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && e.shiftKey) {
        e.preventDefault()
        chatInputRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [])

  // Scroll to bottom + focus input after messages finish loading
  const prevIsLoadingRef = useRef(false)
  useEffect(() => {
    if (prevIsLoadingRef.current && !isLoading && messages.length > 0) {
      scrollToBottom()
      chatInputRef.current?.focus()
    }
    prevIsLoadingRef.current = isLoading
  }, [isLoading, messages.length, scrollToBottom])

  const accentColour = CHAKRA_PALETTE[(persona?.colour_scheme as ChakraColour) ?? 'solar']?.hex ?? '#C9A84C'

  const handleSend = useCallback(
    (text: string) => {
      if (!effectiveSessionId) return
      const optimisticMsg: ChatMessageDto = {
        id: `optimistic-${Date.now()}`,
        session_id: effectiveSessionId,
        role: 'user',
        content: text,
        thinking: null,
        token_count: 0,
        attachments: isIncognito ? null : (attachments.getAttachmentRefs().length > 0 ? attachments.getAttachmentRefs() : null),
        web_search_context: null,
        created_at: new Date().toISOString(),
      }
      useChatStore.getState().appendMessage(optimisticMsg)
      useChatStore.getState().setWaitingForResponse(true)

      if (isIncognito) {
        const allMessages = useChatStore.getState().messages
        sendMessage({
          type: 'chat.incognito.send',
          persona_id: personaId,
          session_id: effectiveSessionId,
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
        })
      } else {
        const attachmentIds = attachments.getAttachmentIds()
        sendMessage({
          type: 'chat.send',
          session_id: effectiveSessionId,
          content: [{ type: 'text', text }],
          ...(attachmentIds.length > 0 ? { attachment_ids: attachmentIds } : {}),
        })
        attachments.clearAttachments()
        setShowUploadBrowser(false)
      }
      setTimeout(() => scrollToBottom(), 50)
    },
    [effectiveSessionId, isIncognito, personaId, scrollToBottom, attachments],
  )

  const handleCancel = useCallback(() => {
    if (!correlationId) return
    sendMessage({ type: 'chat.cancel', correlation_id: correlationId })
  }, [correlationId])

  const handleEdit = useCallback(
    (messageId: string, newContent: string) => {
      if (!effectiveSessionId) return
      if (isIncognito) {
        const store = useChatStore.getState()
        store.truncateAfter(messageId)
        store.updateMessage(messageId, newContent, 0)
        store.setWaitingForResponse(true)
        const allMessages = useChatStore.getState().messages
        sendMessage({
          type: 'chat.incognito.send',
          persona_id: personaId,
          session_id: effectiveSessionId,
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
        })
      } else {
        useChatStore.getState().setWaitingForResponse(true)
        sendMessage({
          type: 'chat.edit',
          session_id: effectiveSessionId,
          message_id: messageId,
          content: [{ type: 'text', text: newContent }],
        })
      }
    },
    [effectiveSessionId, isIncognito, personaId],
  )

  const handleRegenerate = useCallback(() => {
    if (!effectiveSessionId) return
    if (isIncognito) {
      const store = useChatStore.getState()
      const msgs = store.messages
      const lastAssistant = [...msgs].reverse().find((m) => m.role === 'assistant')
      if (lastAssistant) store.deleteMessage(lastAssistant.id)
      store.setWaitingForResponse(true)
      const allMessages = useChatStore.getState().messages
      sendMessage({
        type: 'chat.incognito.send',
        persona_id: personaId,
        session_id: effectiveSessionId,
        messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
      })
    } else {
      useChatStore.getState().setWaitingForResponse(true)
      sendMessage({ type: 'chat.regenerate', session_id: effectiveSessionId })
    }
  }, [effectiveSessionId, isIncognito, personaId])

  if (!effectiveSessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
        Loading chat...
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-white/6 px-4 py-2">
        <div className="flex items-center gap-2">
          {isIncognito && (
            <span className="rounded bg-white/8 px-1.5 py-0.5 text-[10px] font-mono text-white/40" title="Messages are not saved">
              INCOGNITO
            </span>
          )}
          <span className="max-w-[400px] truncate text-[13px] text-white/40">
            {isIncognito ? (persona?.name ?? 'Incognito') : (sessionTitle ?? 'New chat')}
          </span>
        </div>
        <ContextStatusPill status={contextStatus} fillPercentage={contextFillPercentage} />
      </div>

      {error && (
        <div className="border-b border-red-500/20 bg-red-500/5 px-4 py-2 text-[13px]">
          <span className="text-red-400">{error.userMessage}</span>
          {error.recoverable && (
            <button type="button" onClick={handleRegenerate}
              className="ml-3 rounded border border-red-500/30 px-2 py-0.5 text-[12px] text-red-300 hover:bg-red-500/10">
              Retry
            </button>
          )}
          <button type="button" onClick={() => useChatStore.getState().clearError()}
            className="ml-2 text-[12px] text-white/30 hover:text-white/50">
            Dismiss
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <span className="text-[13px] text-white/20">Loading messages...</span>
        </div>
      ) : (
        <MessageList
          messages={messages} streamingContent={streamingContent} streamingThinking={streamingThinking}
          streamingWebSearchContext={streamingWebSearchContext} activeToolCalls={activeToolCalls}
          isWaitingForResponse={isWaitingForResponse}
          isStreaming={isStreaming} accentColour={accentColour} highlighter={highlighter}
          containerRef={containerRef} showScrollButton={showScrollButton} onScrollToBottom={scrollToBottom}
          onEdit={handleEdit} onRegenerate={handleRegenerate}
        />
      )}

      {showUploadBrowser && (
        <UploadBrowserPanel
          personaId={personaId}
          onSelect={(file) => attachments.addExistingFile(file)}
          onClose={() => setShowUploadBrowser(false)}
        />
      )}

      <ChatInput ref={chatInputRef} onSend={handleSend} onCancel={handleCancel}
        onFilesSelected={(files) => files.forEach((f) => attachments.addFile(f))} onToggleBrowser={() => setShowUploadBrowser((v) => !v)}
        isStreaming={isStreaming} disabled={isLoading} hasPendingUploads={attachments.hasPending}
        attachmentStrip={attachments.hasAttachments ? (
          <AttachmentStrip attachments={attachments.pendingAttachments} onRemove={attachments.removeAttachment} />
        ) : undefined}
        toolBar={effectiveSessionId ? (
          <ToolToggles
            sessionId={effectiveSessionId}
            disabledToolGroups={disabledToolGroups}
            onToggle={(groups) => useChatStore.getState().setDisabledToolGroups(groups)}
            disabled={isStreaming}
            modelSupportsTools={modelSupportsTools}
            modelSupportsReasoning={modelSupportsReasoning}
            reasoningOverride={reasoningOverride}
            personaReasoningDefault={personaReasoningDefault}
            onReasoningToggle={(override) => useChatStore.getState().setReasoningOverride(override)}
          />
        ) : undefined}
      />
    </div>
  )
}
