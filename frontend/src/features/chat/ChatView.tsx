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
import { useBookmarks } from '../../core/hooks/useBookmarks'
import { bookmarksApi } from '../../core/api/bookmarks'
import { BookmarkModal } from './BookmarkModal'
import { ChatBookmarkList } from './ChatBookmarkList'

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
  const [isResolvingSession, setIsResolvingSession] = useState(false)

  const isIncognito = searchParams.get('incognito') === '1'
  const incognitoIdRef = useRef(`incognito-${crypto.randomUUID()}`)
  const effectiveSessionId = isIncognito ? incognitoIdRef.current : sessionId

  useEffect(() => {
    setIsResolvingSession(false)
    if (isIncognito) return
    if (!personaId || sessionId) return
    setIsResolvingSession(true)

    const forceNew = searchParams.get('new') === '1'

    if (forceNew) {
      chatApi
        .createSession(personaId)
        .then((session) => navigate(`/chat/${personaId}/${session.id}`, { replace: true }))
        .finally(() => { setIsResolvingSession(false) })
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
      .finally(() => { setIsResolvingSession(false) })
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
  const { containerRef, bottomRef, showScrollButton, scrollToBottom } = useAutoScroll(isStreaming)

  // Scroll to a specific message by ID (used for bookmarks and ?msg= param)
  const scrollToMessage = useCallback((messageId: string) => {
    requestAnimationFrame(() => {
      const el = document.getElementById(`msg-${messageId}`)
      if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' })
        el.nextElementSibling?.classList.add('bookmark-flash')
        setTimeout(() => el.nextElementSibling?.classList.remove('bookmark-flash'), 2000)
      }
    })
  }, [])

  // React to ?msg= param changes when chat is already loaded
  const msgParam = searchParams.get('msg')
  const prevMsgParam = useRef<string | null>(null)
  useEffect(() => {
    if (msgParam && msgParam !== prevMsgParam.current && !isLoading && messages.length > 0) {
      scrollToMessage(msgParam)
    }
    prevMsgParam.current = msgParam
  }, [msgParam, isLoading, messages.length, scrollToMessage])

  // Bookmarks
  const { bookmarks, setBookmarks } = useBookmarks(effectiveSessionId)
  const bookmarkedMessageIds = new Set(bookmarks.map((b) => b.message_id))
  const [bookmarkTargetMsgId, setBookmarkTargetMsgId] = useState<string | null>(null)
  const [bookmarksExpanded, setBookmarksExpanded] = useState(false)

  useChatStream(effectiveSessionId ?? null)

  useEffect(() => {
    const store = useChatStore.getState()
    store.reset(effectiveSessionId)

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

  // Handle session_expired: redirect to a new chat with the same persona
  useEffect(() => {
    if (error?.errorCode === 'session_expired' && personaId && !isIncognito) {
      useChatStore.getState().clearError()
      navigate(`/chat/${personaId}?new=1`, { replace: true })
    }
  }, [error, personaId, isIncognito, navigate])

  // Scroll to specific message or bottom after loading
  const prevIsLoadingRef = useRef(false)
  useEffect(() => {
    if (prevIsLoadingRef.current && !isLoading && messages.length > 0) {
      const targetMsg = searchParams.get('msg')
      if (targetMsg) {
        scrollToMessage(targetMsg)
      } else {
        scrollToBottom()
      }
      chatInputRef.current?.focus()
    }
    prevIsLoadingRef.current = isLoading
  }, [isLoading, messages.length, scrollToBottom])

  const accentColour = CHAKRA_PALETTE[(persona?.colour_scheme as ChakraColour) ?? 'solar']?.hex ?? '#C9A84C'

  const handleSend = useCallback(
    (text: string) => {
      if (!effectiveSessionId) return
      const optimisticMsg: ChatMessageDto = {
        id: `optimistic-${crypto.randomUUID()}`,
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
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        {isResolvingSession && (
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
        )}
        <span className="text-[13px] text-white/20">
          {isResolvingSession ? 'Resolving session...' : 'Loading chat...'}
        </span>
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
        <div className="flex items-center gap-2">
          {/* Chat-local bookmarks dropdown */}
          {bookmarks.length > 0 && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setBookmarksExpanded((v) => !v)}
                className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-mono transition-colors ${bookmarksExpanded ? 'bg-gold/10 text-gold' : 'text-white/30 hover:text-white/50'}`}
                title="Bookmarks in this chat"
              >
                <svg width="12" height="12" viewBox="0 0 14 14" fill={bookmarksExpanded ? 'currentColor' : 'none'}>
                  <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                </svg>
                {bookmarks.length}
              </button>
              {bookmarksExpanded && (
                <ChatBookmarkList
                  bookmarks={bookmarks}
                  onScrollTo={(msgId) => scrollToMessage(msgId)}
                  onClose={() => setBookmarksExpanded(false)}
                  onBookmarksReordered={setBookmarks}
                  onBookmarkUpdated={(updated) => setBookmarks((prev) => prev.map((b) => b.id === updated.id ? updated : b))}
                />
              )}
            </div>
          )}
          <ContextStatusPill status={contextStatus} fillPercentage={contextFillPercentage} />
        </div>
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
          containerRef={containerRef} bottomRef={bottomRef} showScrollButton={showScrollButton} onScrollToBottom={scrollToBottom}
          onEdit={handleEdit} onRegenerate={handleRegenerate}
          bookmarkedMessageIds={bookmarkedMessageIds}
          onBookmark={(msgId) => setBookmarkTargetMsgId(msgId)}
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

      {/* Bookmark creation modal */}
      <BookmarkModal
        isOpen={bookmarkTargetMsgId !== null}
        onClose={() => setBookmarkTargetMsgId(null)}
        onSave={async (title, scope) => {
          if (!bookmarkTargetMsgId || !effectiveSessionId || !personaId) return
          await bookmarksApi.create({
            session_id: effectiveSessionId,
            message_id: bookmarkTargetMsgId,
            persona_id: personaId,
            title,
            scope,
          })
          setBookmarkTargetMsgId(null)
        }}
        accentColour={accentColour}
      />
    </div>
  )
}
