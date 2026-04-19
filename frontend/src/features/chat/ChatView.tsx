import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useOutletContext, useParams, useSearchParams } from 'react-router-dom'
import { chatApi, type ChatMessageDto } from '../../core/api/chat'
import { llmApi } from '../../core/api/llm'
import type { UserModalTab } from '../../app/components/user-modal/UserModal'
import { eventBus } from '../../core/websocket/eventBus'
import { Topics } from '../../core/types/events'
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
import { KnowledgeDropdown } from './KnowledgeDropdown'
import { ToolPopover } from './ToolPopover'
import { useMcpStore } from '../mcp/mcpStore'
import { useIntegrationsStore } from '../integrations/store'
import { useMemoryEvents } from '../memory/useMemoryEvents'
import { useMemoryStore } from '../../core/store/memoryStore'
import { ArtefactRail } from '../artefact/ArtefactRail'
import { ArtefactSidebar } from '../artefact/ArtefactSidebar'
import { ArtefactOverlay } from '../artefact/ArtefactOverlay'
import { useArtefactEvents } from '../artefact/useArtefactEvents'
import { useArtefactStore } from '../../core/store/artefactStore'
import { artefactApi } from '../../core/api/artefact'
import { ChatIntegrationsPanel } from '../integrations/ChatIntegrationsPanel'
import { useViewport } from '../../core/hooks/useViewport'
import { useVoiceSettingsStore } from '../voice/stores/voiceSettingsStore'
import { resolveSTTEngine, resolveTTSEngine, resolveTTSIntegrationId } from '../voice/engines/resolver'
import { resolveGapMs as resolveTtsGapMs } from '../voice/engines/defaults'
import { useVoicePipeline } from '../voice/stores/voicePipelineStore'
import { useCtrlSpace } from '../voice/hooks/useCtrlSpace'
import { voicePipeline } from '../voice/pipeline/voicePipeline'
import { TranscriptionOverlay } from '../voice/components/TranscriptionOverlay'
import { setActiveReader } from '../voice/components/ReadAloudButton'
import { audioPlayback } from '../voice/infrastructure/audioPlayback'
import { refreshMistralVoices } from '../integrations/plugins/mistral_voice/voices'
import { useSecretsStore } from '../integrations/secretsStore'
import { createStreamingSentencer } from '../voice/pipeline/streamingSentencer'
import {
  cancelStreamingAutoRead,
  getActiveStreamingAutoRead,
  setActiveStreamingAutoRead,
  type StreamingAutoReadSession,
} from '../voice/pipeline/streamingAutoReadControl'
import { applyModulation, resolveModulation } from '../voice/pipeline/applyModulation'
import type { NarratorMode, SpeechSegment } from '../voice/types'
import { useConversationModeStore } from '../voice/stores/conversationModeStore'
import { useConversationMode } from '../voice/hooks/useConversationMode'
import { ConversationModeButton } from '../voice/components/ConversationModeButton'
import { HoldToKeepTalking } from '../voice/components/HoldToKeepTalking'

interface ChatViewProps {
  persona: PersonaDto | null
}

const EMPTY_MEMORY_ENTRIES: never[] = []

export function ChatView({ persona }: ChatViewProps) {
  const { personaId, sessionId } = useParams<{ personaId: string; sessionId?: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { pendingArtefactId?: string } | null }

  // Empty-state detection: if the user has no LLM connections yet, render
  // a CTA instead of the chat UI. We fetch on mount and live-refresh on
  // connection create/remove events.
  const [connectionCount, setConnectionCount] = useState<number | null>(null)
  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      llmApi.listConnections()
        .then((conns) => { if (!cancelled) setConnectionCount(conns.length) })
        .catch(() => { if (!cancelled) setConnectionCount(null) })
    }
    refresh()
    const unsubs = [
      eventBus.on(Topics.LLM_CONNECTION_CREATED, refresh),
      eventBus.on(Topics.LLM_CONNECTION_REMOVED, refresh),
    ]
    return () => {
      cancelled = true
      unsubs.forEach((u) => u())
    }
  }, [])
  const { isMobile } = useViewport()
  const chatInputRef = useRef<ChatInputHandle>(null)
  const [isLoading, setIsLoading] = useState(false)
  // True for one render when arriving from the new-chat redirect — instructs
  // the post-load focus effect to fire even though the navigate causes a
  // remount that drops the imperative focus call's effect.
  const [pendingFocus, setPendingFocus] = useState(false)
  const [showUploadBrowser, setShowUploadBrowser] = useState(false)
  const [modelSupportsTools, setModelSupportsTools] = useState(true)
  const [modelSupportsReasoning, setModelSupportsReasoning] = useState(true)
  const [isResolvingSession, setIsResolvingSession] = useState(false)
  const [showIncognitoNotice, setShowIncognitoNotice] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [resolveAttempt, setResolveAttempt] = useState(0)
  const [showKnowledge, setShowKnowledge] = useState(false)
  const [toolPopoverOpen, setToolPopoverOpen] = useState(false)
  // Mobile-only expandable tray for Tool-Toggles (< lg:). Desktop renders them inline.
  const [mobileToolsOpen, setMobileToolsOpen] = useState(false)

  // Voice integration state — "enabled" is determined by whether an STT engine is registered and ready
  const autoSendTranscription = useVoiceSettingsStore((s) => s.autoSendTranscription)
  const sttEnabled = !!resolveSTTEngine()?.isReady()
  const pipelineState = useVoicePipeline((s) => s.state)
  const setPipelineState = useVoicePipeline((s) => s.setState)
  const [transcription, setTranscription] = useState('')
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
          // Flag the post-load effect so the prompt input gets focused once
          // the new session has loaded — focusing here would race the navigate.
          setPendingFocus(true)
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
  const contextUsedTokens = useChatStore((s) => s.contextUsedTokens)
  const contextMaxTokens = useChatStore((s) => s.contextMaxTokens)
  const error = useChatStore((s) => s.error)
  const sessionTitle = useChatStore((s) => s.sessionTitle)
  const disabledToolGroups = useChatStore((s) => s.disabledToolGroups)
  const reasoningOverride = useChatStore((s) => s.reasoningOverride)

  const personaReasoningDefault = persona?.reasoning_enabled ?? false

  const attachments = useAttachments(personaId)
  const highlighter = useHighlighter()
  const { containerRef, bottomRef, showScrollButton, scrollToBottom } = useAutoScroll()

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
    // unique_id format: "<connection_id>:<model_slug>" (see INSIGHTS.md INS-004).
    const connectionId = uid.split(':')[0]
    const modelSlug = uid.split(':').slice(1).join(':')
    llmApi
      .listConnectionModels(connectionId)
      .then((models) => {
        if (isCancelled()) return
        const model = models.find((m) => m.model_id === modelSlug)
        setModelSupportsTools(model?.supports_tool_calls ?? false)
        setModelSupportsReasoning(model?.supports_reasoning ?? false)
      })
      .catch((err: unknown) => {
        if (isCancelled()) return
        console.error('Failed to load model capabilities', err)
        setModelSupportsTools(true)
      })
  }, [])
  // TODO Phase 8: capabilities should ideally come from PersonaDto / SessionDto so we can drop the listConnectionModels call entirely.

  useChatStream(effectiveSessionId ?? null)
  useMemoryEvents(persona?.id ?? null)
  useArtefactEvents(effectiveSessionId ?? null)
  const artefactSidebarOpen = useArtefactStore((s) => s.sidebarOpen)
  const artefactCount = useArtefactStore((s) => s.artefacts.length)
  const toggleArtefactSidebar = useArtefactStore((s) => s.toggleSidebar)
  const memoryEntries = useMemoryStore((s) => s.uncommittedEntries[personaId ?? ''] ?? EMPTY_MEMORY_ENTRIES)
  const memoryCount = memoryEntries.length
  const mcpSessionTools = useMcpStore((s) => s.sessionGateways)
  const mcpExcludedGateways = new Set(persona?.mcp_config?.excluded_gateways ?? [])
  const mcpExcludedServers = new Set(persona?.mcp_config?.excluded_servers ?? [])
  const mcpExcludedTools = new Set(persona?.mcp_config?.excluded_tools ?? [])
  const mcpToolCount = mcpSessionTools
    .filter((e) => !mcpExcludedGateways.has(e.namespace))
    .reduce((acc, e) => acc + e.tools.filter((t) =>
      !mcpExcludedServers.has(`${e.namespace}:${t.server_name}`) && !mcpExcludedTools.has(t.name)
    ).length, 0)
  // Integration tool count for the badge
  const intDefinitions = useIntegrationsStore((s) => s.definitions)
  const intConfigs = useIntegrationsStore((s) => s.configs)
  const integrationToolCount = intDefinitions.filter((d) => intConfigs[d.id]?.enabled && d.has_tools).length * 2 // get_toys + control per integration
  const totalToolCount = mcpToolCount + integrationToolCount
  const { openPersonaOverlay, openModal } = useOutletContext<{
    openPersonaOverlay: (personaId: string | null, tab?: string) => void
    openModal?: (tab: UserModalTab) => void
  }>()

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
      .then((bundle) => {
        if (cancelled) return
        useChatStore.getState().setMessages(bundle.messages)
        // Hydrate the context-window indicator from the session's
        // persisted metrics so a long chat does not show 0% when
        // revisited without running a new inference.
        useChatStore.getState().setContextStatus(bundle.context_status)
        useChatStore.getState().setContextFillPercentage(bundle.context_fill_percentage)
        useChatStore.getState().setContextTokens(
          bundle.context_used_tokens ?? 0,
          bundle.context_max_tokens ?? 0,
        )
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
        applyModelCapabilities(persona?.model_unique_id, isCancelled)
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

  // Scroll to specific message or bottom after loading. Depends on
  // `highlighter` so the scroll fires once Shiki is ready — otherwise
  // code-block highlighting lands asynchronously *after* the initial
  // scroll and leaves the viewport above the true bottom.
  const prevIsLoadingRef = useRef(false)
  useEffect(() => {
    if (prevIsLoadingRef.current && !isLoading && messages.length > 0 && highlighter) {
      const targetMsg = searchParams.get('msg')
      if (targetMsg) {
        scrollToMessage(targetMsg)
      } else {
        scrollToBottom()
      }
      chatInputRef.current?.focus()
    }
    prevIsLoadingRef.current = isLoading
  }, [isLoading, messages.length, scrollToBottom, scrollToMessage, searchParams, highlighter])

  // Focus the prompt input when a brand-new chat is opened. New sessions
  // start with zero messages so the load effect above does not fire — handle
  // this case explicitly via `pendingFocus`.
  useEffect(() => {
    if (pendingFocus && sessionId && !isLoading) {
      chatInputRef.current?.focus()
      setPendingFocus(false)
    }
  }, [pendingFocus, sessionId, isLoading])

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
    // Stopping inference must also kill in-flight TTS synthesis and any
    // audio already queued, otherwise the user hears the tail of content
    // that was never shown on screen.
    cancelStreamingAutoRead()
    setActiveReader(null, 'idle')
    setPartialSavedNotice(true)
    setTimeout(() => setPartialSavedNotice(false), 6000)
  }, [correlationId])

  const handleEdit = useCallback(
    (messageId: string, newContent: string) => {
      if (!effectiveSessionId) return
      if (messageId.startsWith('optimistic-')) {
        // The server has not yet confirmed this message, so we cannot reference
        // it by its final ID. The edit affordance is normally disabled in this
        // state (see UserBubble), but surface a visible notice as a safety net.
        console.warn('Refusing to edit optimistic message — ID not yet swapped by server')
        useNotificationStore.getState().addNotification({
          level: 'info',
          title: 'Please wait',
          message: 'Message is still syncing, please wait a moment.',
          duration: 4000,
        })
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

  // Voice pipeline callbacks — registered once on mount. handleSend and
  // autoSendTranscription are read through refs so that re-renders (which
  // happen e.g. every time `attachments` produces a new object reference) do
  // NOT cause the effect to re-run; a re-run would fire the cleanup which
  // calls voicePipeline.dispose(), which in turn cancels any in-flight
  // getUserMedia and leaves the mic spinner stuck.
  const handleSendRef = useRef(handleSend)
  useEffect(() => { handleSendRef.current = handleSend }, [handleSend])
  const autoSendTranscriptionRef = useRef(autoSendTranscription)
  useEffect(() => { autoSendTranscriptionRef.current = autoSendTranscription }, [autoSendTranscription])

  useEffect(() => {
    voicePipeline.setCallbacks({
      onStateChange: setPipelineState,
      onTranscription: (text) => {
        // In conversational mode we never surface the transcription overlay
        // and always auto-send — the dedicated VAD path (useConversationMode)
        // owns the send, so PTT's onTranscription should not double-fire.
        // This branch handles only the PTT pipeline.
        if (useConversationModeStore.getState().active) return
        setTranscription(text)
        if (autoSendTranscriptionRef.current && text.trim()) {
          // Auto-send mode: briefly show the transcription, then send.
          setTimeout(() => {
            handleSendRef.current(text)
            setTranscription('')
          }, 800)
        } else {
          // Default (push-to-talk review) mode: put text in input for editing before send.
          chatInputRef.current?.setText(text)
          setTimeout(() => setTranscription(''), 1500)
        }
      },
    })
    return () => voicePipeline.dispose()
  }, [setPipelineState])

  // Streaming auto-read: as ChatContentDelta events accumulate into
  // streamingContent, we incrementally cut sentence-safe prefixes with
  // StreamingSentencer, synthesise each via the active TTS integration,
  // and enqueue the resulting audio in order. This avoids the audible
  // wait-for-stream-end a non-streaming implementation would have.
  //
  // Ordering: synthesis is async, but audio must play in arrival order.
  // We serialise via a promise chain so audio N+1 only enqueues after N.
  //
  // Cancellation: each session carries a `cancelled` flag that is flipped
  // when the user barges (mic press / voice toggle handlers). In-flight
  // synth promises check the flag before enqueueing, so stale audio never
  // reaches audioPlayback.
  const prevIsStreamingRef = useRef(false)

  // Diagnostic refs — pair with the [LLM-infer] / [TTS-infer] / [TTS-play]
  // logs. Remove once the "TTS starts only at end of inference" bug is
  // understood.
  const prevIsWaitingRef = useRef(false)
  const llmStartTsRef = useRef<number | null>(null)

  // Conversation-mode active state — read once here so we can override
  // auto_read while the user is in a live conversation.
  const conversationActive = useConversationModeStore((s) => s.active)
  const conversationPhase = useConversationModeStore((s) => s.phase)
  const conversationIsHolding = useConversationModeStore((s) => s.isHolding)
  const setConversationHolding = useConversationModeStore((s) => s.setHolding)
  const enterConversationMode = useConversationModeStore((s) => s.enter)
  const exitConversationMode = useConversationModeStore((s) => s.exit)

  // Resolve everything we need to start a streaming auto-read session.
  // Returns null if auto-read is disabled or any dependency is missing.
  const resolveAutoReadSession = useCallback(async (
    messageId: string,
  ): Promise<StreamingAutoReadSession | null> => {
    // Conversational mode implicitly forces auto-read on; outside of it,
    // honour the persona's stored preference.
    const autoRead = !!persona?.voice_config?.auto_read || conversationActive
    if (!autoRead) return null

    const tts = resolveTTSEngine(persona)
    if (!tts || !tts.isReady()) return null

    // Resolve the integration ID the same way the engine is resolved so the
    // voice_id lookup reads from the matching persona.integration_configs
    // sub-dict (xAI's voice_id lives under integration_configs.xai_voice, not
    // under whichever integration happens to be first enabled).
    const ttsIntegrationId = resolveTTSIntegrationId(persona)
    const activeTTS = ttsIntegrationId
      ? intDefinitions.find((d) => d.id === ttsIntegrationId)
      : undefined
    if (!activeTTS) return null

    const voiceId = persona?.integration_configs?.[activeTTS.id]?.voice_id as string | undefined
    if (!voiceId) return null

    if (tts.voices.length === 0) {
      const apiKey = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
      if (apiKey) await refreshMistralVoices(apiKey)
    }
    const voice = tts.voices.find((v) => v.id === voiceId)
    if (!voice) return null

    const narratorMode: NarratorMode = persona?.voice_config?.narrator_mode ?? 'off'
    const rawNarratorVoiceId = persona?.integration_configs?.[activeTTS.id]?.narrator_voice_id as string | null | undefined
    const narratorVoiceId = rawNarratorVoiceId ?? null
    const narratorVoice = narratorVoiceId
      ? (tts.voices.find((v) => v.id === narratorVoiceId) ?? voice)
      : voice

    const gapMs = resolveTtsGapMs(
      activeTTS.id,
      intConfigs?.[activeTTS.id]?.config as Record<string, unknown> | undefined,
    )

    const modulation = resolveModulation(persona?.voice_config)

    return {
      tts,
      voice,
      narratorVoice,
      mode: narratorMode,
      gapMs,
      messageId,
      sentencer: createStreamingSentencer(narratorMode),
      lastTextLength: 0,
      chain: Promise.resolve(),
      cancelled: false,
      modulation,
    }
  }, [persona, intDefinitions, intConfigs, conversationActive])

  // Enqueue synthesis of new segments onto the session's promise chain.
  // Serialises the async synths so audio is enqueued in arrival order, even
  // when a later synth finishes faster than an earlier one.
  const queueSynth = useCallback((session: StreamingAutoReadSession, segments: SpeechSegment[]) => {
    for (const segment of segments) {
      session.chain = session.chain.then(async () => {
        if (session.cancelled) return
        try {
          const targetVoice = segment.type === 'voice' ? session.voice : session.narratorVoice
          const preview = segment.text.slice(0, 40).replace(/\s+/g, ' ')
          // Diagnostic logs — remove once the "TTS starts only at end of
          // inference" bug is understood. Track each segment through synth
          // initiation, synth completion, playback start, and playback end.
          const inferStart = performance.now()
          console.log(`[TTS-infer] start "${preview}"`)
          const audio = await session.tts.synthesise(segment.text, targetVoice)
          console.log(`[TTS-infer] done  "${preview}" ${Math.round(performance.now() - inferStart)}ms`)
          if (session.cancelled) return
          audioPlayback.enqueue(audio, applyModulation(segment, session.modulation))
        } catch (err) {
          if (session.cancelled) return
          console.error('[ChatView] Streaming TTS synthesis failed:', err)
          const isAuthError = err instanceof Error && (err.message.includes('401') || err.message.includes('Unauthorized'))
          useNotificationStore.getState().addNotification({
            level: 'error',
            title: 'Read aloud failed',
            message: isAuthError
              ? "Couldn't read reply aloud — check your TTS API key."
              : "Couldn't read reply aloud — check the console for details.",
          })
          session.cancelled = true
          audioPlayback.stopAll()
          setActiveReader(null, 'idle')
        }
      }).catch(() => {})
    }
  }, [])

  const feedStreamingAutoRead = useCallback((newText: string) => {
    const session = getActiveStreamingAutoRead()
    if (!session) return
    if (newText.length <= session.lastTextLength) return
    const delta = newText.slice(session.lastTextLength)
    session.lastTextLength = newText.length
    const segments = session.sentencer.push(delta)
    if (segments.length > 0) queueSynth(session, segments)
  }, [queueSynth])

  // Start- and end-of-stream transitions. Opens a fresh session on start,
  // flushes and closes it on end.
  useEffect(() => {
    const wasStreaming = prevIsStreamingRef.current
    prevIsStreamingRef.current = isStreaming

    if (isStreaming && !wasStreaming) {
      cancelStreamingAutoRead()
      const messageId = correlationId ?? `stream-${Date.now()}`
      void (async () => {
        const session = await resolveAutoReadSession(messageId)
        if (!session) return
        // Stream may have ended while we were resolving (short replies).
        if (!useChatStore.getState().isStreaming) return
        audioPlayback.setCallbacks({
          gapMs: session.gapMs,
          onSegmentStart: () => {
            if (getActiveStreamingAutoRead()?.messageId === messageId) {
              setActiveReader(messageId, 'playing')
            }
          },
          onFinished: () => {
            if (getActiveStreamingAutoRead()?.messageId === messageId) {
              setActiveReader(null, 'idle')
            }
          },
        })
        setActiveStreamingAutoRead(session)
        setActiveReader(messageId, 'synthesising')
        const initial = useChatStore.getState().streamingContent
        if (initial) feedStreamingAutoRead(initial)
      })()
    }

    if (!isStreaming && wasStreaming) {
      const session = getActiveStreamingAutoRead()
      if (!session) return
      const remaining = session.sentencer.flush()
      if (remaining.length > 0) queueSynth(session, remaining)
      // Keep the session ref live until the chain has fully drained. If we
      // null it synchronously, a barge during the drain period calls
      // cancelStreamingAutoRead but finds no session — so it cannot set
      // `cancelled`, and any in-flight synth promises go on enqueuing audio
      // after stopAll was called, causing the queue to keep playing through
      // an interruption. Clearing on .finally() keeps the barge path able
      // to cancel pending synth even after the stream has ended.
      session.chain = session.chain.then(() => {
        if (session.cancelled) return
        audioPlayback.closeStream()
      }).catch(() => {}).finally(() => {
        if (getActiveStreamingAutoRead() === session) {
          setActiveStreamingAutoRead(null)
        }
      })
    }
  }, [isStreaming, correlationId, resolveAutoReadSession, feedStreamingAutoRead, queueSynth])

  // Diagnostic log for the LLM side of the pipeline. Pairs with
  // [TTS-infer] / [TTS-play]. Remove once bug understood.
  //   start       — request sent, waiting for first token
  //   first-token — first content token arrived (isStreaming flipped true)
  //   end         — stream finished
  useEffect(() => {
    const wasWaiting = prevIsWaitingRef.current
    const wasStreaming = prevIsStreamingRef.current
    prevIsWaitingRef.current = isWaitingForResponse

    if (isWaitingForResponse && !wasWaiting) {
      llmStartTsRef.current = performance.now()
      console.log('[LLM-infer] start')
    }
    if (isStreaming && !wasStreaming) {
      const start = llmStartTsRef.current
      const ttft = start !== null ? ` ttft=${Math.round(performance.now() - start)}ms` : ''
      console.log(`[LLM-infer] first-token${ttft}`)
    }
    if (!isStreaming && wasStreaming) {
      const start = llmStartTsRef.current
      const total = start !== null ? ` total=${Math.round(performance.now() - start)}ms` : ''
      console.log(`[LLM-infer] end${total}`)
      llmStartTsRef.current = null
    }
  }, [isStreaming, isWaitingForResponse])

  // Diagnostic — long-task observer. Reports every synchronous block on the
  // main thread longer than 50 ms while the LLM stream runs. A cluster of
  // these during streaming is the smoking gun for the "TTS hangs until LLM
  // ends" bug: main-thread starvation blocks await resolution. Remove once
  // the render-cost hotspot is fixed.
  useEffect(() => {
    if (!isStreaming && !isWaitingForResponse) return
    if (typeof PerformanceObserver === 'undefined') return
    let total = 0
    let count = 0
    const LONGTASK_FLOOR_MS = 100 // only log tasks over this many ms, to cut noise
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        total += entry.duration
        count++
        if (entry.duration >= LONGTASK_FLOOR_MS) {
          console.log(`[longtask] ${Math.round(entry.duration)}ms`)
        }
      }
    })
    try { observer.observe({ entryTypes: ['longtask'] }) } catch { /* not supported */ }
    return () => {
      observer.disconnect()
      console.log(`[longtask] summary: ${count} tasks totalling ${Math.round(total)}ms over this stream`)
    }
  }, [isStreaming, isWaitingForResponse])

  // Mid-stream: each streamingContent update pushes its delta through the
  // sentencer and queues any emitted segments for synthesis.
  useEffect(() => {
    if (!isStreaming) return
    feedStreamingAutoRead(streamingContent)
  }, [streamingContent, isStreaming, feedStreamingAutoRead])

  // Cleanup on unmount.
  useEffect(() => {
    return () => { cancelStreamingAutoRead() }
  }, [])

  // Mic handlers
  const handleMicPress = useCallback(() => {
    // Cancel any active Read Aloud (stop playback + discard pending synthesis,
    // including the streaming auto-read path so its in-flight synth promises
    // are dropped before they reach audioPlayback).
    cancelStreamingAutoRead()
    setActiveReader(null, 'idle')
    audioPlayback.stopAll()
    voicePipeline.startRecording('push-to-talk')
  }, [])

  const handleMicRelease = useCallback(() => {
    voicePipeline.stopRecording()
  }, [])

  const handleStopVoice = useCallback(() => {
    voicePipeline.stopRecording()
    voicePipeline.stopPlayback()
  }, [])

  const handleVoiceToggle = useCallback(() => {
    if (pipelineState.phase === 'listening' || pipelineState.phase === 'recording') {
      voicePipeline.stopRecording()
    } else {
      cancelStreamingAutoRead()
      setActiveReader(null, 'idle')
      audioPlayback.stopAll()
      voicePipeline.startRecording('push-to-talk')
    }
  }, [pipelineState.phase])

  // Ctrl+Space shortcut: hold = push-to-talk, tap = toggle push-to-talk recording
  useCtrlSpace({
    enabled: sttEnabled && !conversationActive,
    onHoldStart: handleMicPress,
    onHoldEnd: handleMicRelease,
    onTap: handleVoiceToggle,
  })

  // Conversational-mode availability: requires a ready STT engine AND a
  // persona with an enabled TTS integration + a resolved voice id.
  const ttsConfigured = (() => {
    if (!persona) return false
    const tts = resolveTTSEngine(persona)
    if (!tts || !tts.isReady()) return false
    const ttsIntegrationId = resolveTTSIntegrationId(persona)
    const activeTTS = ttsIntegrationId
      ? intDefinitions.find((d) => d.id === ttsIntegrationId)
      : undefined
    if (!activeTTS) return false
    const voiceId = persona.integration_configs?.[activeTTS.id]?.voice_id as string | undefined
    return !!voiceId
  })()
  const conversationAvailable = sttEnabled && ttsConfigured

  // Conv-mode controller: owns VAD + auto-send + barge on speech-start.
  useConversationMode({
    sessionId: effectiveSessionId ?? null,
    available: conversationAvailable,
    onSend: handleSend,
  })

  const handleToggleConversation = useCallback(() => {
    if (conversationActive) {
      exitConversationMode()
      return
    }
    if (!conversationAvailable) return
    // Stop any PTT recording before grabbing the mic for VAD.
    try { voicePipeline.stopRecording() } catch { /* not active */ }
    enterConversationMode()
  }, [conversationActive, conversationAvailable, enterConversationMode, exitConversationMode])

  if (connectionCount === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-6 text-center">
        <div className="space-y-3">
          <p className="text-white/80">
            You haven't configured an LLM connection yet.
          </p>
          <button
            type="button"
            onClick={() => openModal?.('llm-providers')}
            className="inline-flex items-center px-4 py-2 rounded bg-purple/70 text-white"
          >
            Set up now
          </button>
        </div>
      </div>
    )
  }

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
            <div
              ref={incognitoInfoRef}
              className="relative"
              onMouseEnter={isMobile ? undefined : () => setIncognitoInfoOpen(true)}
              onMouseLeave={isMobile ? undefined : () => setIncognitoInfoOpen(false)}
            >
              <button
                type="button"
                onClick={isMobile ? () => setIncognitoInfoOpen((v) => !v) : undefined}
                title={isMobile ? 'Messages are not saved — tap for details' : 'Messages are not saved'}
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
                  className="absolute left-0 top-full mt-2 z-50 w-72 rounded-md border border-gold/25 bg-[#0b0a08] lg:bg-[#0b0a08]/95 lg:backdrop-blur-sm shadow-sm lg:shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2.5 text-[12px] text-white/70 font-mono leading-relaxed"
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
          <div
            className="relative"
            onMouseEnter={isMobile ? undefined : () => setShowKnowledge(true)}
            onMouseLeave={isMobile ? undefined : () => setShowKnowledge(false)}
          >
            <button
              type="button"
              onClick={isMobile ? () => setShowKnowledge((v) => !v) : undefined}
              className="flex items-center justify-center w-6 h-6 rounded text-[13px] transition-colors"
              style={
                showKnowledge
                  ? {
                      background: 'rgba(140,118,215,0.1)',
                      border: '1px solid rgba(140,118,215,0.6)',
                      boxShadow: '0 0 8px rgba(140,118,215,0.4)',
                    }
                  : { background: 'rgba(140,118,215,0.1)' }
              }
              title="Ad-hoc Knowledge"
            >
              🎓
            </button>
            {persona && effectiveSessionId && (
              <KnowledgeDropdown
                personaId={persona.id}
                personaName={persona.name}
                sessionId={effectiveSessionId}
                isOpen={showKnowledge}
                onClose={() => setShowKnowledge(false)}
                readonly={!isMobile}
              />
            )}
          </div>
          <ConversationModeButton
            active={conversationActive}
            available={conversationAvailable}
            phase={conversationPhase}
            onToggle={handleToggleConversation}
          />
          <div className="relative">
            <button
              type="button"
              onClick={() => setToolPopoverOpen((v) => !v)}
              className="relative rounded px-1.5 py-0.5 text-sm transition-colors hover:bg-white/5"
              title="Active tools"
            >
              🔧
              {totalToolCount > 0 && (
                <span
                  className="absolute -right-1.5 -top-1 rounded-full px-1 text-[8px] font-bold"
                  style={{ backgroundColor: 'rgba(166,218,149,0.8)', color: '#0f0d16' }}
                >
                  {totalToolCount}
                </span>
              )}
            </button>
            {toolPopoverOpen && (
              <ToolPopover
                disabledToolGroups={disabledToolGroups}
                personaMcpConfig={persona?.mcp_config ?? null}
                onClose={() => setToolPopoverOpen(false)}
              />
            )}
          </div>
          <span className="max-w-[40vw] md:max-w-[400px] truncate text-[13px] text-white/40">
            {isIncognito ? (persona?.name ?? 'Incognito') : (sessionTitle ?? 'New chat')}
          </span>
        </div>
        {/* Desktop topbar indicators */}
        <div className="hidden lg:flex items-center gap-2">
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
          <ContextStatusPill
            status={contextStatus}
            fillPercentage={contextFillPercentage}
            usedTokens={contextUsedTokens}
            maxTokens={contextMaxTokens}
          />
        </div>

        {/* Mobile topbar indicators — compact icon-only pills */}
        <div className="flex lg:hidden items-center gap-1.5">
          {artefactCount > 0 && (
            <button
              type="button"
              onClick={toggleArtefactSidebar}
              className="flex items-center gap-1 rounded-full border border-gold/20 bg-gold/5 px-1.5 py-0.5 text-[10px] font-mono text-gold"
              title={`${artefactCount} artefact${artefactCount === 1 ? '' : 's'}`}
            >
              <svg width="11" height="11" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round">
                <path d="M2.5 2.5H9L11.5 5V11.5H2.5V2.5Z" />
                <path d="M9 2.5V5H11.5" />
              </svg>
              {artefactCount}
            </button>
          )}
          <button
            type="button"
            onClick={() => personaId && openPersonaOverlay(personaId, 'memories')}
            className={`flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-mono ${
              memoryCount > 0
                ? 'border-green-500/20 bg-green-500/5 text-green-400'
                : 'border-white/8 bg-white/3 text-white/30'
            }`}
            title={`${memoryCount} memory entries`}
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
              <path d="M8 2C5.8 2 4 3.8 4 6c0 1.5.8 2.8 2 3.5V11h4V9.5c1.2-.7 2-2 2-3.5 0-2.2-1.8-4-4-4z" />
              <path d="M6 12.5h4M6.5 14h3" />
            </svg>
            {memoryCount}
          </button>
          <span
            className={`flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-mono ${
              contextStatus === 'green' ? 'border-green-500/20 bg-white/3 text-white/30'
              : contextStatus === 'yellow' ? 'border-yellow-400/20 bg-yellow-400/5 text-yellow-300'
              : contextStatus === 'orange' ? 'border-orange-500/20 bg-orange-500/5 text-orange-400'
              : 'border-red-500/20 bg-red-500/5 text-red-400'
            }`}
            title={`Context: ${Math.round(contextFillPercentage * 100)}%`}
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
              <circle cx="8" cy="8" r="6" />
              <path d="M8 4v4l2.5 2.5" />
            </svg>
            {contextStatus === 'green' ? '' : `${Math.round(contextFillPercentage * 100)}%`}
          </span>
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
              sttEnabled={sttEnabled}
              persona={persona}
            />
          )}

          {showUploadBrowser && (
            <UploadBrowserPanel
              personaId={personaId}
              onSelect={(file) => attachments.addExistingFile(file)}
              onClose={() => setShowUploadBrowser(false)}
            />
          )}

          {transcription && <TranscriptionOverlay text={transcription} autoSend={autoSendTranscription} />}
          {conversationActive && (conversationPhase === 'user-speaking' || conversationPhase === 'held') && (
            <HoldToKeepTalking
              isHolding={conversationIsHolding}
              onHoldStart={() => setConversationHolding(true)}
              onHoldEnd={() => setConversationHolding(false)}
            />
          )}
          <ChatInput ref={chatInputRef} onSend={handleSend} onCancel={handleCancel}
            onFilesSelected={(files) => files.forEach((f) => attachments.addFile(f))} onToggleBrowser={() => setShowUploadBrowser((v) => !v)}
            isStreaming={isStreaming} disabled={isLoading} hasPendingUploads={attachments.hasPending}
            sttEnabled={sttEnabled}
            voicePhase={pipelineState.phase}
            volumeLevel={0}
            onMicPress={handleMicPress}
            onMicRelease={handleMicRelease}
            onStopRecording={handleStopVoice}
            attachmentStrip={attachments.hasAttachments ? (
              <AttachmentStrip attachments={attachments.pendingAttachments} onRemove={attachments.removeAttachment} />
            ) : undefined}
            toolBar={effectiveSessionId ? (
              <>
                {/* Desktop: inline tool toggles. */}
                <div className="hidden lg:block">
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
                    filteredMcpToolCount={mcpToolCount}
                    reasoningLocked={conversationActive}
                  />
                </div>
                <div className="hidden lg:block">
                  <ChatIntegrationsPanel persona={persona} />
                </div>
                {/* Mobile: icon-only button row + collapsible tool toggles. */}
                <div className="lg:hidden">
                  <div className="flex items-center gap-1.5">
                    {/* Tools toggle */}
                    <button
                      type="button"
                      onClick={() => setMobileToolsOpen((v) => !v)}
                      className={`flex h-8 w-8 items-center justify-center rounded border transition-colors ${
                        mobileToolsOpen
                          ? 'border-gold/30 bg-gold/10 text-gold shadow-[0_0_8px_rgba(249,226,175,0.3)]'
                          : 'border-white/10 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/85'
                      }`}
                      aria-expanded={mobileToolsOpen}
                      aria-label="Toggle tool tray"
                    >
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9.5 2.8L13.2 6.5L6.5 13.2L2.1 13.9L2.8 9.5L9.5 2.8Z" />
                        <path d="M8.5 4L12 7.5" />
                      </svg>
                    </button>
                    {/* Attach file */}
                    <button
                      type="button"
                      onClick={() => chatInputRef.current?.openFilePicker()}
                      className="flex h-8 w-8 items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85"
                      aria-label="Attach file"
                    >
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                        <path d="M7.5 2C5 2 3 4 3 6.5V11C3 13.5 5 15.5 7.5 15.5C10 15.5 12 13.5 12 11V5.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                      </svg>
                    </button>
                    {/* Camera capture */}
                    <button
                      type="button"
                      onClick={() => chatInputRef.current?.openCamera()}
                      className="flex h-8 w-8 items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85"
                      aria-label="Take photo"
                    >
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round">
                        <path d="M2 5.5C2 4.95 2.45 4.5 3 4.5H5L6 3H10L11 4.5H13C13.55 4.5 14 4.95 14 5.5V12C14 12.55 13.55 13 13 13H3C2.45 13 2 12.55 2 12V5.5Z" />
                        <circle cx="8" cy="8.5" r="2.5" />
                      </svg>
                    </button>
                    {/* Browse uploads */}
                    <button
                      type="button"
                      onClick={() => setShowUploadBrowser((v) => !v)}
                      className="flex h-8 w-8 items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85"
                      aria-label="Browse uploads"
                    >
                      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                        <path d="M2 4.5V12.5C2 13.05 2.45 13.5 3 13.5H13C13.55 13.5 14 13.05 14 12.5V6.5C14 5.95 13.55 5.5 13 5.5H8L6.5 3.5H3C2.45 3.5 2 3.95 2 4.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                      </svg>
                    </button>
                  </div>
                  <ChatIntegrationsPanel persona={persona} />
                  {mobileToolsOpen && (
                    <div className="mt-2 rounded border border-white/8 bg-white/4 px-3 py-2">
                      <div className="[&>div]:flex-col [&>div]:items-start [&>div]:gap-2">
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
                          filteredMcpToolCount={mcpToolCount}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </>
            ) : undefined}
          />
          <ArtefactOverlay />
        </div>
        {/* Desktop rail: visible only when sidebar is collapsed. ArtefactRail
            itself is scoped to `lg:` so it stays hidden on mobile. */}
        {!artefactSidebarOpen && artefactCount > 0 && <ArtefactRail />}
        {/* Sidebar: in-flow panel on desktop, right-sheet overlay on mobile.
            Always rendered when open — the component handles its own layout. */}
        {artefactSidebarOpen && effectiveSessionId && (
          <ArtefactSidebar sessionId={effectiveSessionId} />
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
