import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useChatStore } from '../../core/store/chatStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import { sendMessage } from '../../core/websocket/connection'
import type { ArtefactRef } from '../../core/api/chat'
import { ResponseTagBuffer } from '../integrations/responseTagProcessor'
import { useIntegrationsStore } from '../integrations/store'
import { getActiveGroup } from './responseTaskGroup'
import { useCockpitStore } from './cockpit/cockpitStore'

let activeTagBuffer: ResponseTagBuffer | null = null

// Module-level handler exported for unit testing. The hook wires this into
// the event bus; tests call it directly without mounting a component.
export function handleChatEvent(
  event: BaseEvent,
  sendMessageFn: typeof sendMessage,
  sessionId: string | null,
): void {
  const getStore = useChatStore.getState
  const p = event.payload as Record<string, unknown>

  switch (event.type) {
    case Topics.CHAT_STREAM_STARTED: {
      if (p.session_id !== sessionId) return
      getStore().startStreaming(event.correlation_id)
      // Create tag buffer for this streaming session
      const enabledIds = useIntegrationsStore.getState().getEnabledIds()
      if (enabledIds.length > 0) {
        activeTagBuffer = new ResponseTagBuffer((placeholder, replacement) => {
          getStore().replaceInStreamingContent(placeholder, replacement)
        })
      } else {
        activeTagBuffer = null
      }
      break
    }
    case Topics.CHAT_CONTENT_DELTA: {
      const g = getActiveGroup()
      if (!g || g.id !== event.correlation_id) {
        console.debug(`[useChatStream] drop CHAT_CONTENT_DELTA (no matching group, id=${event.correlation_id})`)
        return
      }
      const rawDelta = p.delta as string
      // Tag buffer still lives here — it transforms deltas before storage.
      const visibleDelta = activeTagBuffer ? activeTagBuffer.process(rawDelta) : rawDelta
      g.onDelta(visibleDelta)
      break
    }
    case Topics.CHAT_THINKING_DELTA: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().appendStreamingThinking(p.delta as string)
      break
    }
    case Topics.CHAT_STREAM_SLOW: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().setStreamingSlow(true)
      break
    }
    case Topics.CHAT_VISION_DESCRIPTION: {
      getStore().upsertVisionDescription(event.correlation_id, {
        file_id: p.file_id as string,
        display_name: p.display_name as string,
        model_id: p.model_id as string,
        status: p.status as 'pending' | 'success' | 'error',
        text: (p.text as string | null) ?? null,
        error: (p.error as string | null) ?? null,
      })
      break
    }
    case Topics.CHAT_TOOL_CALL_STARTED: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().addToolCall({
        id: p.tool_call_id as string,
        toolName: p.tool_name as string,
        arguments: p.arguments as Record<string, unknown>,
        status: 'running',
      })
      break
    }
    case Topics.CHAT_TOOL_CALL_COMPLETED: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().completeToolCall(p.tool_call_id as string)
      const artefactRef = p.artefact_ref as ArtefactRef | null | undefined
      if (artefactRef) {
        getStore().appendArtefactRef(artefactRef)
      }
      break
    }
    case Topics.CHAT_WEB_SEARCH_CONTEXT: {
      if (event.correlation_id !== getStore().correlationId) return
      const items = p.items as Array<{ title: string; url: string; snippet: string }>
      getStore().setStreamingWebSearchContext(items)
      break
    }
    case Topics.CHAT_STREAM_ENDED: {
      if (p.session_id !== sessionId) return
      const g = getActiveGroup()
      if (g && g.id === event.correlation_id) g.onStreamEnd()
      // Flush incomplete tag buffer
      if (activeTagBuffer) {
        const remainder = activeTagBuffer.flush()
        if (remainder) getStore().appendStreamingContent(remainder)
        activeTagBuffer = null
      }
      const contextStatus = (p.context_status as 'green' | 'yellow' | 'orange' | 'red') ?? 'green'
      const fillPercentage = (p.context_fill_percentage as number) ?? 0
      const usedTokens = (p.context_used_tokens as number | undefined) ?? 0
      const maxTokens = (p.context_max_tokens as number | undefined) ?? 0
      const rawStatus = (p.status as string | undefined) ?? 'completed'
      const messageStatus: 'completed' | 'aborted' | 'refused' =
        rawStatus === 'refused'
          ? 'refused'
          : rawStatus === 'aborted'
            ? 'aborted'
            : 'completed'
      const ttft = (p.time_to_first_token_ms as number | undefined) ?? null
      const tps = (p.tokens_per_second as number | undefined) ?? null
      const genDuration = (p.generation_duration_ms as number | undefined) ?? null
      const providerName = (p.provider_name as string | undefined) ?? null
      const modelName = (p.model_name as string | undefined) ?? null

      // Finalise the streamed message whenever the backend persisted
      // it — even on cancelled/error runs, the backend now saves the
      // partial content so we do not throw away tokens the user has
      // already seen. The ``status`` is still surfaced so the bubble
      // can be badged as interrupted if we want to.
      // Refused messages may have no content — still persist them so
      // the refusal band shows immediately without a page refresh.
      const backendMessageId = p.message_id as string | undefined
      const content = getStore().streamingContent
      const thinking = getStore().streamingThinking
      const webSearchContext = getStore().streamingWebSearchContext
      const knowledgeContext = getStore().streamingKnowledgeContext
      const artefactRefs = getStore().streamingArtefactRefs
      const refusalText = getStore().streamingRefusalText
      const toolCalls = getStore().activeToolCalls
      // Auto-read trigger: if the session has auto-read on and the message
      // completed normally with content, signal the ReadAloudButton for this
      // messageId to start playback. Lives here (not in AssistantMessage)
      // because the messageId changes from optimistic to backend at commit
      // time, which remounts the component and loses any local transition.
      if (
        backendMessageId
        && content
        && messageStatus === 'completed'
        && getStore().autoRead
      ) {
        useCockpitStore.getState().requestAutoRead(backendMessageId)
      }

      if (backendMessageId && (content || thinking || messageStatus === 'refused')) {
        getStore().finishStreaming(
          {
            id: backendMessageId,
            session_id: sessionId ?? '',
            role: 'assistant',
            content,
            thinking: thinking || null,
            token_count: 0,
            attachments: null,
            web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
            knowledge_context: knowledgeContext.length > 0 ? knowledgeContext : null,
            artefact_refs: artefactRefs.length > 0 ? artefactRefs : null,
            tool_calls: toolCalls.length > 0
              ? toolCalls.map((tc) => ({
                  tool_call_id: tc.id,
                  tool_name: tc.toolName,
                  arguments: tc.arguments,
                  success: tc.status === 'done',
                }))
              : null,
            refusal_text: refusalText || null,
            created_at: new Date().toISOString(),
            status: messageStatus,
            time_to_first_token_ms: ttft,
            tokens_per_second: tps,
            generation_duration_ms: genDuration,
            provider_name: providerName,
            model_name: modelName,
          },
          contextStatus,
          fillPercentage,
          usedTokens,
          maxTokens,
        )
      } else {
        getStore().cancelStreaming()
      }
      getStore().setContextStatus(contextStatus)
      getStore().setContextFillPercentage(fillPercentage)
      getStore().setContextTokens(usedTokens, maxTokens)
      break
    }
    case Topics.CHAT_STREAM_ERROR: {
      const errorCode = p.error_code as string
      // Session-level errors arrive outside a streaming context —
      // they carry their own correlation id that the frontend never
      // saw, so we let them through unconditionally. This includes
      // rejections from handle_chat_edit that fire before any stream
      // has started (invalid_edit, session_busy, edit_target_missing,
      // edit_failed).
      const sessionLevelCodes = new Set([
        'session_expired',
        'invalid_edit',
        'edit_target_missing',
        'edit_failed',
      ])
      const isSessionError = sessionLevelCodes.has(errorCode)
      if (!isSessionError && event.correlation_id !== getStore().correlationId) return

      const recoverable = p.recoverable as boolean
      const userMessage = p.user_message as string
      getStore().setError({
        errorCode,
        recoverable,
        userMessage,
      })
      getStore().setWaitingForResponse(false)

      if (errorCode === 'refusal') {
        getStore().setStreamingRefusalText(userMessage)
      }

      // Session-level errors have their own banner path (ChatView
      // renders them inline above the composer); everything else
      // surfaces through the toast system so the user is not left
      // staring at a silently broken reply. Recoverable errors get
      // an inline Regenerate action bound to the session that was
      // current when the error arrived.
      if (!isSessionError) {
        const sessionIdAtError = sessionId
        const title = (() => {
          if (errorCode === 'refusal') return 'Request declined'
          if (recoverable) return 'Response interrupted'
          return 'Error'
        })()
        const action = recoverable && sessionIdAtError
          ? {
              label: 'Regenerate',
              onClick: () => {
                sendMessageFn({
                  type: 'chat.regenerate',
                  session_id: sessionIdAtError,
                })
              },
            }
          : undefined
        useNotificationStore.getState().addNotification({
          level: 'error',
          title,
          message: userMessage,
          action,
        })
      }
      break
    }
    case Topics.CHAT_MESSAGE_CREATED: {
      if (p.session_id !== sessionId) return
      const clientId = p.client_message_id as string | undefined
      if (clientId) {
        const idx = getStore().messages.findIndex((m) => m.id === clientId)
        if (idx !== -1) {
          getStore().swapMessageId(clientId, p.message_id as string)
          break
        }
      }
      // Fallback: append if we have no matching optimistic entry
      // (e.g. another tab, or a server-initiated user message).
      getStore().appendMessage({
        id: p.message_id as string,
        session_id: sessionId ?? '',
        role: p.role as 'user' | 'assistant',
        content: p.content as string,
        thinking: null,
        token_count: (p.token_count as number) ?? 0,
        attachments: null,
        web_search_context: null,
        knowledge_context: null,
        created_at: new Date().toISOString(),
      })
      break
    }
    case Topics.CHAT_MESSAGES_TRUNCATED: {
      if (p.session_id !== sessionId) return
      getStore().truncateAfter(p.after_message_id as string)
      break
    }
    case Topics.CHAT_MESSAGE_UPDATED: {
      if (p.session_id !== sessionId) return
      getStore().updateMessage(p.message_id as string, p.content as string, p.token_count as number)
      break
    }
    case Topics.CHAT_MESSAGE_DELETED: {
      if (p.session_id !== sessionId) return
      getStore().deleteMessage(p.message_id as string)
      break
    }
    case Topics.CHAT_SESSION_TITLE_UPDATED: {
      if (p.session_id !== sessionId) return
      getStore().setSessionTitle(p.title as string)
      break
    }
    case Topics.CHAT_SESSION_TOOLS_UPDATED: {
      // Legacy event — no-op, superseded by CHAT_SESSION_TOGGLES_UPDATED
      break
    }
    case Topics.CHAT_SESSION_TOGGLES_UPDATED: {
      if (p.session_id !== sessionId) return
      if (typeof p.tools_enabled === 'boolean') getStore().setToolsEnabled(p.tools_enabled)
      if (typeof p.auto_read === 'boolean') getStore().setAutoRead(p.auto_read)
      if ('reasoning_override' in p) {
        const ro = p.reasoning_override
        getStore().setReasoningOverride(typeof ro === 'boolean' ? ro : null)
      }
      break
    }
  }
}

export function useChatStream(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    // TODO Phase 8: the old inference.lock.* events have been removed.
    // Re-add an equivalent hook once the new event shape (tied to a
    // connection_id) lands.
    const handleEvent = (event: BaseEvent) => handleChatEvent(event, sendMessage, sessionId)

    const unsub = eventBus.on('chat.*', handleEvent)
    return () => {
      unsub()
    }
  }, [sessionId])
}
