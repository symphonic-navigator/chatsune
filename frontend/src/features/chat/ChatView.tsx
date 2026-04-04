import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { chatApi, type ChatMessageDto } from '../../core/api/chat'
import { sendMessage } from '../../core/websocket/connection'
import { useChatStore } from '../../core/store/chatStore'
import { useChatStream } from './useChatStream'
import { useAutoScroll } from './useAutoScroll'
import { useHighlighter } from './useMarkdown'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { ContextStatusPill } from './ContextStatusPill'
import { CHAKRA_PALETTE, type ChakraColour } from '../../core/types/chakra'
import type { PersonaDto } from '../../core/types/persona'

interface ChatViewProps {
  persona: PersonaDto | null
}

export function ChatView({ persona }: ChatViewProps) {
  const { sessionId } = useParams<{ personaId: string; sessionId?: string }>()
  const [isLoading, setIsLoading] = useState(false)

  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const correlationId = useChatStore((s) => s.correlationId)
  const streamingContent = useChatStore((s) => s.streamingContent)
  const streamingThinking = useChatStore((s) => s.streamingThinking)
  const contextStatus = useChatStore((s) => s.contextStatus)
  const contextFillPercentage = useChatStore((s) => s.contextFillPercentage)
  const error = useChatStore((s) => s.error)
  const sessionTitle = useChatStore((s) => s.sessionTitle)

  const highlighter = useHighlighter()
  const { containerRef, showScrollButton, scrollToBottom } = useAutoScroll(isStreaming)

  useChatStream(sessionId ?? null)

  useEffect(() => {
    const store = useChatStore.getState()
    store.reset()

    if (!sessionId) return

    setIsLoading(true)
    chatApi
      .getMessages(sessionId)
      .then((msgs: ChatMessageDto[]) => {
        useChatStore.getState().setMessages(msgs)
        setTimeout(() => scrollToBottom(), 50)
      })
      .catch(() => {})
      .finally(() => setIsLoading(false))

    chatApi
      .getSession(sessionId)
      .then((session) => {
        useChatStore.getState().setSessionTitle(session.title)
      })
      .catch(() => {})
  }, [sessionId, scrollToBottom])

  const accentColour = CHAKRA_PALETTE[(persona?.colour_scheme as ChakraColour) ?? 'solar']?.hex ?? '#C9A84C'

  const handleSend = useCallback(
    (text: string) => {
      if (!sessionId) return
      const optimisticMsg: ChatMessageDto = {
        id: `optimistic-${Date.now()}`,
        session_id: sessionId,
        role: 'user',
        content: text,
        thinking: null,
        token_count: 0,
        created_at: new Date().toISOString(),
      }
      useChatStore.getState().appendMessage(optimisticMsg)
      sendMessage({
        type: 'chat.send',
        session_id: sessionId,
        content: [{ type: 'text', text }],
      })
      setTimeout(() => scrollToBottom(), 50)
    },
    [sessionId, scrollToBottom],
  )

  const handleCancel = useCallback(() => {
    if (!correlationId) return
    sendMessage({ type: 'chat.cancel', correlation_id: correlationId })
  }, [correlationId])

  const handleEdit = useCallback(
    (messageId: string, newContent: string) => {
      if (!sessionId) return
      sendMessage({
        type: 'chat.edit',
        session_id: sessionId,
        message_id: messageId,
        content: [{ type: 'text', text: newContent }],
      })
    },
    [sessionId],
  )

  const handleRegenerate = useCallback(() => {
    if (!sessionId) return
    sendMessage({ type: 'chat.regenerate', session_id: sessionId })
  }, [sessionId])

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
        Select or start a chat session
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-white/6 px-4 py-2">
        <span className="max-w-[400px] truncate text-[13px] text-white/40">
          {sessionTitle ?? 'New chat'}
        </span>
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
          isStreaming={isStreaming} accentColour={accentColour} highlighter={highlighter}
          containerRef={containerRef} showScrollButton={showScrollButton} onScrollToBottom={scrollToBottom}
          onEdit={handleEdit} onRegenerate={handleRegenerate}
        />
      )}

      <ChatInput onSend={handleSend} onCancel={handleCancel} isStreaming={isStreaming} disabled={isLoading} />
    </div>
  )
}
