import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useChatStore } from '../../core/store/chatStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'

export function useChatStream(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    const store = useChatStore.getState

    const handleEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>

      switch (event.type) {
        case Topics.CHAT_STREAM_STARTED: {
          if (p.session_id !== sessionId) return
          store().startStreaming(event.correlation_id)
          break
        }
        case Topics.CHAT_CONTENT_DELTA: {
          if (event.correlation_id !== store().correlationId) return
          store().appendStreamingContent(p.delta as string)
          break
        }
        case Topics.CHAT_THINKING_DELTA: {
          if (event.correlation_id !== store().correlationId) return
          store().appendStreamingThinking(p.delta as string)
          break
        }
        case Topics.CHAT_TOOL_CALL_STARTED: {
          if (event.correlation_id !== store().correlationId) return
          store().addToolCall({
            id: p.tool_call_id as string,
            toolName: p.tool_name as string,
            arguments: p.arguments as Record<string, unknown>,
            status: 'running',
          })
          break
        }
        case Topics.CHAT_TOOL_CALL_COMPLETED: {
          if (event.correlation_id !== store().correlationId) return
          store().completeToolCall(p.tool_call_id as string)
          break
        }
        case Topics.CHAT_WEB_SEARCH_CONTEXT: {
          if (event.correlation_id !== store().correlationId) return
          const items = p.items as Array<{ title: string; url: string; snippet: string }>
          store().setStreamingWebSearchContext(items)
          break
        }
        case Topics.CHAT_STREAM_ENDED: {
          if (p.session_id !== sessionId) return
          const status = p.status as string
          const contextStatus = (p.context_status as 'green' | 'yellow' | 'orange' | 'red') ?? 'green'
          const fillPercentage = (p.context_fill_percentage as number) ?? 0

          if (status === 'completed') {
            const content = store().streamingContent
            const thinking = store().streamingThinking
            const webSearchContext = store().streamingWebSearchContext
            if (content) {
              store().finishStreaming(
                {
                  id: `streaming-${Date.now()}`,
                  session_id: sessionId,
                  role: 'assistant',
                  content,
                  thinking: thinking || null,
                  token_count: 0,
                  web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
                  created_at: new Date().toISOString(),
                },
                contextStatus,
                fillPercentage,
              )
            } else {
              store().cancelStreaming()
            }
          } else {
            store().cancelStreaming()
          }
          store().setContextStatus(contextStatus)
          store().setContextFillPercentage(fillPercentage)
          break
        }
        case Topics.CHAT_STREAM_ERROR: {
          const errorCode = p.error_code as string
          // Session-level errors arrive outside a streaming context
          const isSessionError = errorCode === 'session_expired'
          if (!isSessionError && event.correlation_id !== store().correlationId) return
          store().setError({
            errorCode,
            recoverable: p.recoverable as boolean,
            userMessage: p.user_message as string,
          })
          break
        }
        case Topics.CHAT_MESSAGES_TRUNCATED: {
          if (p.session_id !== sessionId) return
          store().truncateAfter(p.after_message_id as string)
          break
        }
        case Topics.CHAT_MESSAGE_UPDATED: {
          if (p.session_id !== sessionId) return
          store().updateMessage(p.message_id as string, p.content as string, p.token_count as number)
          break
        }
        case Topics.CHAT_MESSAGE_DELETED: {
          if (p.session_id !== sessionId) return
          store().deleteMessage(p.message_id as string)
          break
        }
        case Topics.CHAT_SESSION_TITLE_UPDATED: {
          if (p.session_id !== sessionId) return
          store().setSessionTitle(p.title as string)
          break
        }
        case Topics.CHAT_SESSION_TOOLS_UPDATED: {
          if (p.session_id !== sessionId) return
          store().setDisabledToolGroups(p.disabled_tool_groups as string[])
          break
        }
      }
    }

    const unsub = eventBus.on('chat.*', handleEvent)
    return unsub
  }, [sessionId])
}
