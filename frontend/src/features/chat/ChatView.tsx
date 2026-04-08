import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
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
import { useNotificationStore } from '../../core/store/notificationStore'
import { BookmarkModal } from './BookmarkModal'
import { ChatBookmarkList } from './ChatBookmarkList'
import { JournalBadge } from './JournalBadge'
import { useMemoryEvents } from '../memory/useMemoryEvents'
import { InferenceWaitBanner } from './InferenceWaitBanner'
import { ArtefactRail } from '../artefact/ArtefactRail'
import { ArtefactSidebar } from '../artefact/ArtefactSidebar'
import { ArtefactOverlay } from '../artefact/ArtefactOverlay'
import { useArtefactEvents } from '../artefact/useArtefactEvents'
import { useArtefactStore } from '../../core/store/artefactStore'
import { artefactApi } from '../../core/api/artefact'

interface ChatViewProps {
  persona: PersonaDto | null
}

export function ChatView({ persona }: ChatViewProps) {
  const { personaId, sessionId } = useParams<{ personaId: string; sessionId?: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { pendingArtefactId?: string } | null }
  const chatInputRef = useRef<ChatInputHandle>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [showUploadBrowser, setShowUploadBrowser] = useState(false)
  const [modelSupportsTools, setModelSupportsTools] = useState(true)
  const [modelSupportsReasoning, setModelSupportsReasoning] = useState(true)
  const [isResolvingSession, setIsResolvingSession] = useState(false)
  const [showIncognitoNotice, setShowIncognitoNotice] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [resolveAttempt, setResolveAttempt] = useState(0)
  const [partialSavedNotice, setPartialSavedNotice] = useState(false)
  // TODO(optimistic-retry): track failed message IDs and surface a retry button on the bubble.
  // Requires plumbing through MessageList/UserMessage; deferred — top-level error banner already exists.

  const isIncognito = searchParams.get('incognito') === '1'
  const incognitoIdRef = useRef(`incognito-${crypto.randomUUID()}`)
  const effectiveSessionId = isIncognito ? incognitoIdRef.current : sessionId

  useEffect(() => {
    setIsResolvingSession(false)
    setResolveError(null)
    if (isIncognito) return
    if (!personaId || sessionId) return
    setIsResolvingSession(true)

    let cancelled = false
    const forceNew = searchParams.get('new') === '1'

    // 15s safety timeout — if backend hangs, surface a retry option instead of an infinite spinner
    const timeoutId = setTimeout(() => {
      if (cancelled) return
      cancelled = true
      setIsResolvingSession(false)
      setResolveError('Resolving the chat session timed out. Please retry.')
    }, 15_000)

    const finish = () => {
      if (cancelled) return
      clearTimeout(timeoutId)
      setIsResolvingSession(false)
    }

    const fail = (err: unknown) => {
      if (cancelled) return
      console.error('Chat session resolve failed', err)
      cancelled = true
      clearTimeout(timeoutId)
      setIsResolvingSession(false)
      setResolveError('Could not load or create a chat session.')
    }

    if (forceNew) {
      chatApi
        .createSession(personaId)
        .then((session) => {
          if (cancelled) return
          navigate(`/chat/${personaId}/${session.id}`, { replace: true })
        })
        .catch(fail)
        .finally(finish)
      return () => {
        cancelled = true
        clearTimeout(timeoutId)
      }
    }

    chatApi
      .listSessions()
      .then((sessions) => {
        if (cancelled) return undefined
        const latest = sessions
          .filter((s) => s.persona_id === personaId)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
        if (latest) {
          navigate(`/chat/${personaId}/${latest.id}`, { replace: true })
          return undefined
        }
        return chatApi.createSession(personaId).then((session) => {
          if (cancelled) return
          navigate(`/chat/${personaId}/${session.id}`, { replace: true })
        })
      })
      .catch(fail)
      .finally(finish)

    return () => {
      cancelled = true
      clearTimeout(timeoutId)
    }
  }, [searchParams, personaId, sessionId, navigate, isIncognito, resolveAttempt])

  const messages = useChatStore((s) => s.messages)
  const isWaitingForResponse = useChatStore((s) => s.isWaitingForResponse)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const correlationId = useChatStore((s) => s.correlationId)
  const streamingContent = useChatStore((s) => s.streamingContent)
  const streamingThinking = useChatStore((s) => s.streamingThinking)
  const streamingWebSearchContext = useChatStore((s) => s.streamingWebSearchContext)
  const streamingKnowledgeContext = useChatStore((s) => s.streamingKnowledgeContext)
  const activeToolCalls = useChatStore((s) => s.activeToolCalls)
  const contextStatus = useChatStore((s) => s.contextStatus)
  const contextFillPercentage = useChatStore((s) => s.contextFillPercentage)
  const error = useChatStore((s) => s.error)
  const sessionTitle = useChatStore((s) => s.sessionTitle)
  const disabledToolGroups = useChatStore((s) => s.disabledToolGroups)
  const reasoningOverride = useChatStore((s) => s.reasoningOverride)
  const waitingForLock = useChatStore((s) => s.waitingForLock)

  const personaReasoningDefault = persona?.reasoning_enabled ?? false

  // Heartbeat: while an inference is in flight, ping the backend every 5s so
  // the server-side watchdog knows the user is still watching. If the tab is
  // closed, reloaded, or the socket drops, pings stop and the watchdog will
  // auto-cancel the inference after ~12s.
  useEffect(() => {
    if (!correlationId) return
    const handle = window.setInterval(() => {
      sendMessage({ type: 'chat.inference.alive', correlation_id: correlationId })
    }, 5000)
    return () => {
      window.clearInterval(handle)
    }
  }, [correlationId])

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
  const [incognitoInfoOpen, setIncognitoInfoOpen] = useState(false)
  const incognitoInfoRef = useRef<HTMLDivElement>(null)

  // Close incognito info popover on outside click or Escape
  useEffect(() => {
    if (!incognitoInfoOpen) return
    const handleClick = (e: MouseEvent) => {
      if (incognitoInfoRef.current && !incognitoInfoRef.current.contains(e.target as Node)) {
        setIncognitoInfoOpen(false)
      }
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIncognitoInfoOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [incognitoInfoOpen])

  // Show incognito notice once when entering incognito mode
  useEffect(() => {
    setShowIncognitoNotice(isIncognito)
  }, [isIncognito])

  // Look up tool/reasoning capabilities for a model unique id and update local state.
  // Returns a cancel-aware function so callers can ignore stale results on session switch.
  const applyModelCapabilities = useCallback((uid: string | null | undefined, isCancelled: () => boolean) => {
    if (!uid || !uid.includes(':')) return
    const providerId = uid.split(':')[0]
    const modelSlug = uid.split(':').slice(1).join(':')
    llmApi
      .listModels(providerId)
      .then((models) => {
        if (isCancelled()) return
        const model = models.find((m) => m.model_id === modelSlug)
        setModelSupportsTools(model?.supports_tool_calls ?? false)
        setModelSupportsReasoning(model?.supports_reasoning ?? false)
      })
      .catch((err) => {
        if (isCancelled()) return
        console.error('Failed to load model capabilities', err)
        setModelSupportsTools(true)
      })
  }, [])
  // TODO: capabilities should ideally come from PersonaDto / SessionDto so we can drop the llmApi.listModels call entirely.

  useChatStream(effectiveSessionId ?? null)
  useMemoryEvents(persona?.id ?? null)
  useArtefactEvents(effectiveSessionId ?? null)
  const artefactSidebarOpen = useArtefactStore((s) => s.sidebarOpen)
  const artefactCount = useArtefactStore((s) => s.artefacts.length)

  useEffect(() => {
    const store = useChatStore.getState()
    store.reset(effectiveSessionId)
    useArtefactStore.getState().reset()
    setLoadError(null)

    let cancelled = false
    const isCancelled = () => cancelled

    if (isIncognito) {
      applyModelCapabilities(persona?.model_unique_id, isCancelled)
      return () => { cancelled = true }
    }

    if (!sessionId) return () => { cancelled = true }

    setIsLoading(true)
    chatApi
      .getMessages(sessionId)
      .then((msgs: ChatMessageDto[]) => {
        if (cancelled) return
        useChatStore.getState().setMessages(msgs)
      })
      .catch((err) => {
        if (cancelled) return
        console.error('Failed to load chat messages', err)
        setLoadError('Could not load chat history.')
      })
      .finally(() => {
        if (cancelled) return
        setIsLoading(false)
      })

    artefactApi
      .list(sessionId)
      .then((arts) => {
        if (cancelled) return
        useArtefactStore.getState().setArtefacts(arts)
      })
      .catch((err) => {
        if (cancelled) return
        console.error('Failed to load artefacts', err)
        setLoadError((prev) => prev ?? 'Could not load artefacts for this session.')
      })

    chatApi
      .getSession(sessionId)
      .then((session) => {
        if (cancelled) return
        useChatStore.getState().setSessionTitle(session.title)
        useChatStore.getState().setDisabledToolGroups(session.disabled_tool_groups ?? [])
        useChatStore.getState().setReasoningOverride(session.reasoning_override ?? null)
        applyModelCapabilities(session.model_unique_id, isCancelled)
      })
      .catch((err) => {
        if (cancelled) return
        console.error('Failed to load session metadata', err)
        setLoadError((prev) => prev ?? 'Could not load session metadata.')
      })

    return () => { cancelled = true }
  }, [sessionId, scrollToBottom, isIncognito, persona?.id, persona?.model_unique_id, applyModelCapabilities])

  // When navigated here from the global Artefacts tab with a pendingArtefactId,
  // fetch the artefact detail and open the overlay once the session is ready.
  useEffect(() => {
    const pendingId = location.state?.pendingArtefactId
    if (!pendingId || !sessionId) return

    let cancelled = false
    artefactApi.get(sessionId, pendingId)
      .then((detail) => {
        if (cancelled) return
        useArtefactStore.getState().openOverlay(detail)
      })
      .catch((err) => {
        console.error('Failed to open pending artefact', err)
      })
      .finally(() => {
        // Clear the state so a reload does not re-open the overlay.
        window.history.replaceState({}, '')
      })

    return () => { cancelled = true }
  }, [location.state, sessionId])

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

  // Handle session_expired: notify user and redirect to a new chat with the same persona
  useEffect(() => {
    if (error?.errorCode === 'session_expired' && personaId && !isIncognito) {
      const previousSessionUrl = sessionId ? `/chat/${personaId}/${sessionId}` : undefined
      useChatStore.getState().clearError()
      useNotificationStore.getState().addNotification({
        level: 'info',
        title: 'Session expired',
        message: 'Your session has expired. Starting a new chat.',
        duration: 8000,
        ...(previousSessionUrl
          ? {
              action: {
                label: 'View previous chat',
                onClick: () => navigate(previousSessionUrl),
              },
            }
          : {}),
      })
      navigate(`/chat/${personaId}?new=1`, { replace: true })
    }
  }, [error, personaId, sessionId, isIncognito, navigate])

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
  }, [isLoading, messages.length, scrollToBottom, scrollToMessage, searchParams])

  const accentColour = CHAKRA_PALETTE[(persona?.colour_scheme as ChakraColour) ?? 'solar']?.hex ?? '#C9A84C'

  const handleSend = useCallback(
    (text: string) => {
      if (!effectiveSessionId) return
      const clientMessageId = `optimistic-${crypto.randomUUID()}`
      const optimisticMsg: ChatMessageDto = {
        id: clientMessageId,
        session_id: effectiveSessionId,
        role: 'user',
        content: text,
        thinking: null,
        token_count: 0,
        attachments: isIncognito ? null : (attachments.getAttachmentRefs().length > 0 ? attachments.getAttachmentRefs() : null),
        web_search_context: null,
        knowledge_context: null,
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
          client_message_id: clientMessageId,
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
    setPartialSavedNotice(true)
    setTimeout(() => setPartialSavedNotice(false), 6000)
  }, [correlationId])

  const handleEdit = useCallback(
    (messageId: string, newContent: string) => {
      if (!effectiveSessionId) return
      if (messageId.startsWith('optimistic-')) {
        console.warn('Refusing to edit optimistic message — ID not yet swapped by server')
        return
      }
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
        // Optimistically reflect the edit in the store so the bubble does
        // not flash the previous text between closing the editor and the
        // backend's CHAT_MESSAGE_UPDATED arriving. The backend remains
        // authoritative — the truncate/update events will reconcile this.
        const store = useChatStore.getState()
        store.truncateAfter(messageId)
        store.updateMessage(messageId, newContent, 0)
        store.setWaitingForResponse(true)
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
        {resolveError ? (
          <>
            <span className="text-[13px] text-red-400">{resolveError}</span>
            <button
              type="button"
              onClick={() => { setResolveError(null); setResolveAttempt((n) => n + 1) }}
              className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/70 hover:bg-white/5"
            >
              Retry
            </button>
          </>
        ) : (
          <span className="text-[13px] text-white/60">
            {isResolvingSession ? 'Resolving session...' : 'Loading chat...'}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-white/6 px-4 py-2">
        <div className="flex items-center gap-2">
          {isIncognito && (
            <div ref={incognitoInfoRef} className="relative">
              <button
                type="button"
                onClick={() => setIncognitoInfoOpen((v) => !v)}
                title="Messages are not saved — click for details"
                aria-label="Incognito mode information"
                aria-expanded={incognitoInfoOpen}
                className="rounded bg-white/8 px-1.5 py-0.5 text-[10px] font-mono text-white/40 hover:text-gold hover:bg-white/10 transition-colors cursor-pointer"
              >
                INCOGNITO
              </button>
              {incognitoInfoOpen && (
                <div
                  role="dialog"
                  aria-label="Incognito mode explained"
                  className="absolute left-0 top-full mt-2 z-50 w-72 rounded-md border border-gold/25 bg-[#0b0a08]/95 backdrop-blur-sm shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2.5 text-[12px] text-white/70 font-mono leading-relaxed"
                >
                  <div className="mb-1 text-[10px] uppercase tracking-widest text-gold">Incognito mode</div>
                  <p className="mb-1.5">This conversation is ephemeral. Nothing is persisted:</p>
                  <ul className="list-disc list-inside space-y-0.5 text-white/60">
                    <li>No messages stored</li>
                    <li>No memory updated</li>
                    <li>No journal entries</li>
                  </ul>
                  <p className="mt-1.5 text-white/50">Once you close or leave this chat, everything is gone.</p>
                </div>
              )}
            </div>
          )}
          <span className="max-w-[40vw] md:max-w-[400px] truncate text-[13px] text-white/40">
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
          {persona && <JournalBadge personaId={persona.id} />}
          <ContextStatusPill status={contextStatus} fillPercentage={contextFillPercentage} />
        </div>
      </div>

      {error && (
        <div className="border-b border-red-500/20 bg-red-500/5 px-4 py-2 text-[13px]">
          <span className="text-red-400">{error.userMessage}</span>
          {error.recoverable ? (
            <button type="button" onClick={handleRegenerate}
              className="ml-3 rounded border border-red-500/30 px-2 py-0.5 text-[12px] text-red-300 hover:bg-red-500/10">
              Retry
            </button>
          ) : (
            <button type="button" onClick={() => navigate(`/chat/${personaId}?new=1`)}
              className="ml-3 rounded border border-red-500/30 px-2 py-0.5 text-[12px] text-red-300 hover:bg-red-500/10">
              Start new chat
            </button>
          )}
          <button type="button" onClick={() => useChatStore.getState().clearError()}
            className="ml-2 text-[12px] text-white/30 hover:text-white/50">
            Dismiss
          </button>
        </div>
      )}

      {loadError && (
        <div className="border-b border-amber-500/20 bg-amber-500/5 px-4 py-2 text-[13px] text-amber-300">
          {loadError}
          <button
            type="button"
            onClick={() => setLoadError(null)}
            className="ml-3 text-[12px] text-white/40 hover:text-white/60"
          >
            Dismiss
          </button>
        </div>
      )}

      {partialSavedNotice && (
        <div className="border-b border-white/10 bg-white/5 px-4 py-1.5 text-[12px] text-white/60">
          Generation cancelled — partial response saved.
          <button
            type="button"
            onClick={() => setPartialSavedNotice(false)}
            className="ml-3 text-white/35 hover:text-white/60"
          >
            Dismiss
          </button>
        </div>
      )}

      {showIncognitoNotice && (
        <div className="flex items-center justify-between border-b border-white/6 bg-white/5 px-4 py-1.5 text-[12px] text-white/40">
          <span>This conversation will not be saved. A new session starts each time you open this chat.</span>
          <button
            type="button"
            onClick={() => setShowIncognitoNotice(false)}
            className="ml-3 shrink-0 text-white/25 hover:text-white/50 transition-colors"
            aria-label="Dismiss notice"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" />
            </svg>
          </button>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        <div className="flex flex-1 flex-col min-w-0 relative">
          {isLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <span className="text-[13px] text-white/60">Loading messages...</span>
            </div>
          ) : (
            <MessageList
              sessionId={effectiveSessionId ?? null}
              messages={messages} streamingContent={streamingContent} streamingThinking={streamingThinking}
              streamingWebSearchContext={streamingWebSearchContext} streamingKnowledgeContext={streamingKnowledgeContext} activeToolCalls={activeToolCalls}
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

          {waitingForLock && (
            <InferenceWaitBanner holderSource={waitingForLock.holderSource} />
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
          <ArtefactOverlay />
        </div>
        {artefactSidebarOpen ? (
          <ArtefactSidebar sessionId={effectiveSessionId!} />
        ) : (
          artefactCount > 0 && <ArtefactRail />
        )}
      </div>

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
