import { type RefObject } from 'react'
import type { ChatMessageDto } from '../../core/api/chat'
import type { Highlighter } from 'shiki'
import { UserBubble } from './UserBubble'
import { AssistantMessage } from './AssistantMessage'
import { StreamingIndicator } from './StreamingIndicator'
import { RegenerateButton } from './RegenerateButton'

interface MessageListProps {
  messages: ChatMessageDto[]
  streamingContent: string
  streamingThinking: string
  isStreaming: boolean
  accentColour: string
  highlighter: Highlighter | null
  containerRef: RefObject<HTMLDivElement | null>
  showScrollButton: boolean
  onScrollToBottom: () => void
  onEdit: (messageId: string, content: string) => void
  onRegenerate: () => void
}

export function MessageList({
  messages, streamingContent, streamingThinking, isStreaming, accentColour, highlighter,
  containerRef, showScrollButton, onScrollToBottom, onEdit, onRegenerate,
}: MessageListProps) {
  const lastAssistantIdx = messages.findLastIndex((m) => m.role === 'assistant')
  const canRegenerate = !isStreaming && lastAssistantIdx === messages.length - 1

  const scrollbarStyle = `
    .chat-scroll::-webkit-scrollbar { width: 4px; }
    .chat-scroll::-webkit-scrollbar-track { background: transparent; }
    .chat-scroll::-webkit-scrollbar-thumb { background: ${accentColour}33; border-radius: 2px; }
    .chat-scroll::-webkit-scrollbar-thumb:hover { background: ${accentColour}66; }
  `

  return (
    <div ref={containerRef} className="chat-scroll flex-1 overflow-y-auto px-4 py-6">
      <style>{scrollbarStyle}</style>
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-[13px] text-white/20">Start a conversation</p>
          </div>
        )}

        {messages.map((msg, i) => {
          if (msg.role === 'user') {
            return (
              <UserBubble key={msg.id} content={msg.content}
                onEdit={(newContent) => onEdit(msg.id, newContent)} isEditable={!isStreaming} />
            )
          }
          if (msg.role === 'assistant') {
            return (
              <div key={msg.id}>
                <AssistantMessage content={msg.content} thinking={msg.thinking}
                  isStreaming={false} accentColour={accentColour} highlighter={highlighter} />
                {canRegenerate && i === lastAssistantIdx && (
                  <RegenerateButton onClick={onRegenerate} disabled={isStreaming} />
                )}
              </div>
            )
          }
          return null
        })}

        {isStreaming && (
          <div>
            {(streamingThinking || streamingContent) ? (
              <AssistantMessage content={streamingContent} thinking={streamingThinking || null}
                isStreaming={true} accentColour={accentColour} highlighter={highlighter} />
            ) : (
              <StreamingIndicator accentColour={accentColour} />
            )}
          </div>
        )}
      </div>

      {showScrollButton && (
        <button type="button" onClick={onScrollToBottom}
          className="fixed bottom-24 right-8 flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-elevated text-white/40 shadow-lg transition-colors hover:bg-white/10 hover:text-white/60"
          title="Scroll to bottom">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 2V12M7 12L3 8M7 12L11 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  )
}
