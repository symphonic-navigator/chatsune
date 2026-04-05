import { type RefObject, useRef } from 'react'
import type { ChatMessageDto, WebSearchContextItem } from '../../core/api/chat'
import type { Highlighter } from 'shiki'
import { UserBubble } from './UserBubble'
import { AssistantMessage } from './AssistantMessage'
import { StreamingIndicator } from './StreamingIndicator'
import { RegenerateButton } from './RegenerateButton'
import { WebSearchPills } from './WebSearchPills'
import { ToolCallActivity } from './ToolCallActivity'

interface ActiveToolCall {
  id: string
  toolName: string
  arguments: Record<string, unknown>
  status: 'running' | 'done'
}

interface MessageListProps {
  messages: ChatMessageDto[]
  streamingContent: string
  streamingThinking: string
  streamingWebSearchContext: WebSearchContextItem[]
  activeToolCalls: ActiveToolCall[]
  isWaitingForResponse: boolean
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
  messages, streamingContent, streamingThinking, streamingWebSearchContext, activeToolCalls,
  isWaitingForResponse, isStreaming, accentColour, highlighter,
  containerRef, showScrollButton, onScrollToBottom, onEdit, onRegenerate,
}: MessageListProps) {
  const lastAssistantIdx = messages.findLastIndex((m) => m.role === 'assistant')
  const canRegenerate = !isStreaming && lastAssistantIdx === messages.length - 1
  const thinkingExpandedRef = useRef(true)

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
        {messages.length === 0 && !isStreaming && !isWaitingForResponse && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-[13px] text-white/20">Start a conversation</p>
          </div>
        )}

        {messages.map((msg, i) => {
          if (msg.role === 'user') {
            return (
              <UserBubble key={msg.id} content={msg.content} attachments={msg.attachments}
                onEdit={(newContent) => onEdit(msg.id, newContent)} isEditable={!isStreaming} />
            )
          }
          if (msg.role === 'assistant') {
            return (
              <div key={msg.id}>
                {msg.web_search_context && msg.web_search_context.length > 0 && (
                  <WebSearchPills items={msg.web_search_context} />
                )}
                <AssistantMessage content={msg.content} thinking={msg.thinking}
                  isStreaming={false} accentColour={accentColour} highlighter={highlighter}
                  thinkingDefaultExpanded={thinkingExpandedRef.current}
                  onThinkingToggle={(v) => { thinkingExpandedRef.current = v }} />
                {canRegenerate && i === lastAssistantIdx && (
                  <RegenerateButton onClick={onRegenerate} disabled={isStreaming} />
                )}
              </div>
            )
          }
          return null
        })}

        {isWaitingForResponse && !isStreaming && (
          <StreamingIndicator accentColour={accentColour} />
        )}

        {isStreaming && (
          <div>
            {activeToolCalls.filter((tc) => tc.status === 'running').map((tc) => (
              <ToolCallActivity key={tc.id} toolName={tc.toolName} arguments={tc.arguments} />
            ))}
            {streamingWebSearchContext.length > 0 && (
              <WebSearchPills items={streamingWebSearchContext} />
            )}
            {(streamingThinking || streamingContent) ? (
              <AssistantMessage content={streamingContent} thinking={streamingThinking || null}
                isStreaming={true} accentColour={accentColour} highlighter={highlighter}
                thinkingDefaultExpanded={thinkingExpandedRef.current}
                onThinkingToggle={(v) => { thinkingExpandedRef.current = v }} />
            ) : (
              activeToolCalls.length === 0 && <StreamingIndicator accentColour={accentColour} />
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
