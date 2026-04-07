import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useChatStore } from '../../core/store/chatStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'

export function useChatStream(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    const getStore = useChatStore.getState

    const handleEvent = (event: BaseEvent) => {
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
          const status = p.status as string
          const contextStatus = (p.context_status as 'green' | 'yellow' | 'orange' | 'red') ?? 'green'
          const fillPercentage = (p.context_fill_percentage as number) ?? 0

          if (status === 'completed') {
            const content = getStore().streamingContent
            const thinking = getStore().streamingThinking
            const webSearchContext = getStore().streamingWebSearchContext
            const knowledgeContext = getStore().streamingKnowledgeContext
            if (content) {
              getStore().finishStreaming(
                {
                  id: (p.message_id as string) ?? `streaming-${Date.now()}`,
                  session_id: sessionId,
                  role: 'assistant',
                  content,
                  thinking: thinking || null,
                  token_count: 0,
                  attachments: null,
                  web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
                  knowledge_context: knowledgeContext.length > 0 ? knowledgeContext : null,
                  created_at: new Date().toISOString(),
                },
                contextStatus,
                fillPercentage,
              )
            } else {
              getStore().cancelStreaming()
            }
          } else {
            getStore().cancelStreaming()
          }
          getStore().setContextStatus(contextStatus)
          getStore().setContextFillPercentage(fillPercentage)
          break
        }
        case Topics.CHAT_STREAM_ERROR: {
          const errorCode = p.error_code as string
          // Session-level errors arrive outside a streaming context
          const isSessionError = errorCode === 'session_expired'
          if (!isSessionError && event.correlation_id !== getStore().correlationId) return
          getStore().setError({
            errorCode,
            recoverable: p.recoverable as boolean,
            userMessage: p.user_message as string,
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

    const unsub = eventBus.on('chat.*', handleEvent)
    return unsub
  }, [sessionId])
}
