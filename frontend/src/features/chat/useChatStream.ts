import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useChatStore } from '../../core/store/chatStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import { sendMessage } from '../../core/websocket/connection'
import type { ArtefactRef } from '../../core/api/chat'

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
      break
    }
    case Topics.CHAT_CONTENT_DELTA: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().appendStreamingContent(p.delta as string)
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
      getStore().clearWaitingForLock()
      const contextStatus = (p.context_status as 'green' | 'yellow' | 'orange' | 'red') ?? 'green'
      const fillPercentage = (p.context_fill_percentage as number) ?? 0
      const status = (p.status as 'completed' | 'cancelled' | 'error' | 'aborted') ?? 'completed'
      const messageStatus: 'completed' | 'aborted' =
        status === 'aborted' ? 'aborted' : 'completed'

      // Finalise the streamed message whenever the backend persisted
      // it — even on cancelled/error runs, the backend now saves the
      // partial content so we do not throw away tokens the user has
      // already seen. The ``status`` is still surfaced so the bubble
      // can be badged as interrupted if we want to.
      const backendMessageId = p.message_id as string | undefined
      const content = getStore().streamingContent
      const thinking = getStore().streamingThinking
      const webSearchContext = getStore().streamingWebSearchContext
      const knowledgeContext = getStore().streamingKnowledgeContext
      if (backendMessageId && (content || thinking)) {
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
            created_at: new Date().toISOString(),
            status: messageStatus,
          },
          contextStatus,
          fillPercentage,
        )
      } else {
        getStore().cancelStreaming()
      }
      getStore().setContextStatus(contextStatus)
      getStore().setContextFillPercentage(fillPercentage)
      break
    }
    case Topics.CHAT_STREAM_ERROR: {
      getStore().clearWaitingForLock()
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
      if (p.session_id !== sessionId) return
      getStore().setDisabledToolGroups(p.disabled_tool_groups as string[])
      break
    }
  }
}

export function useChatStream(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    const getStore = useChatStore.getState

    const handleInferenceLockEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>
      if (event.type === Topics.INFERENCE_LOCK_WAIT_STARTED) {
        getStore().setWaitingForLock({
          providerId: p.provider_id as string,
          holderSource: p.holder_source as string,
        })
      } else if (event.type === Topics.INFERENCE_LOCK_WAIT_ENDED) {
        getStore().clearWaitingForLock()
      }
    }

    const handleEvent = (event: BaseEvent) => handleChatEvent(event, sendMessage, sessionId)

    const unsub = eventBus.on('chat.*', handleEvent)
    const unsubLock = eventBus.on('inference.*', handleInferenceLockEvent)
    return () => {
      unsub()
      unsubLock()
    }
  }, [sessionId])
}
