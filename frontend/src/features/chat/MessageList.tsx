import { useMemo } from 'react'
import type { ChatMessageDto, WebSearchContextItem } from '../../core/api/chat'
import { useChatStore, type LiveVisionDescription } from '../../core/store/chatStore'
import type { Highlighter } from 'shiki'
import { UserBubble } from './UserBubble'
import { AssistantMessage } from './AssistantMessage'
import { StreamingIndicator } from './StreamingIndicator'
import { WebSearchPills } from './WebSearchPills'
import { KnowledgePills } from './KnowledgePills'
import { ToolCallActivity } from './ToolCallActivity'
import { ArtefactCard } from '../artefact/ArtefactCard'
import type { RetrievedChunkDto } from '../../core/types/knowledge'

interface ActiveToolCall {
  id: string
  toolName: string
  arguments: Record<string, unknown>
  status: 'running' | 'done'
}

interface MessageListProps {
  sessionId: string | null
  messages: ChatMessageDto[]
  streamingContent: string
  streamingThinking: string
  streamingWebSearchContext: WebSearchContextItem[]
  streamingKnowledgeContext: RetrievedChunkDto[]
  activeToolCalls: ActiveToolCall[]
  isWaitingForResponse: boolean
  isStreaming: boolean
  accentColour: string
  highlighter: Highlighter | null
  containerRef: (node: HTMLDivElement | null) => void
  bottomRef: React.RefObject<HTMLDivElement | null>
  showScrollButton: boolean
  onScrollToBottom: () => void
  onEdit: (messageId: string, content: string) => void
  onRegenerate: () => void
  bookmarkedMessageIds: Set<string>
  onBookmark: (messageId: string) => void
}

export function MessageList({
  sessionId, messages, streamingContent, streamingThinking, streamingWebSearchContext, streamingKnowledgeContext, activeToolCalls,
  isWaitingForResponse, isStreaming, accentColour, highlighter,
  containerRef, bottomRef, showScrollButton, onScrollToBottom, onEdit, onRegenerate, bookmarkedMessageIds, onBookmark,
}: MessageListProps) {
  const lastAssistantIdx = messages.findLastIndex((m) => m.role === 'assistant')
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null
  const canRegenerate =
    !isStreaming &&
    lastMsg !== null &&
    (lastMsg.role === 'assistant' || lastMsg.role === 'user')
  const showStandaloneRegenerate = canRegenerate && lastMsg !== null && lastMsg.role === 'user'

  const visionDescriptions = useChatStore((s) => s.visionDescriptions)
  const correlationId = useChatStore((s) => s.correlationId)

  // Live vision descriptions only apply to the most recent user message while
  // a stream is active; persisted messages render from their own snapshots.
  const lastUserMessageId = useMemo(() => {
    const idx = messages.findLastIndex((m) => m.role === 'user')
    return idx === -1 ? null : messages[idx].id
  }, [messages])

  function liveDescriptionsForMessage(messageId: string): Record<string, LiveVisionDescription> | undefined {
    if (!correlationId || messageId !== lastUserMessageId) return undefined
    const result: Record<string, LiveVisionDescription> = {}
    for (const [key, payload] of Object.entries(visionDescriptions)) {
      const sepIndex = key.indexOf(':')
      if (sepIndex === -1) continue
      const corr = key.slice(0, sepIndex)
      const fileId = key.slice(sepIndex + 1)
      if (corr === correlationId) {
        result[fileId] = payload
      }
    }
    return Object.keys(result).length > 0 ? result : undefined
  }

  const scrollbarStyle = `
    .chat-scroll::-webkit-scrollbar { width: 8px; }
    .chat-scroll::-webkit-scrollbar-track { background: transparent; }
    .chat-scroll::-webkit-scrollbar-thumb { background: ${accentColour}33; border-radius: 4px; }
    .chat-scroll::-webkit-scrollbar-thumb:hover { background: ${accentColour}66; }
  `

  return (
    <div className="relative flex-1">
      <div ref={containerRef} className="chat-scroll absolute inset-0 overflow-y-auto px-3 py-6 lg:px-4">
      <style>{scrollbarStyle}</style>
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.length === 0 && !isStreaming && !isWaitingForResponse && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-[13px] text-white/20">Start a conversation</p>
          </div>
        )}

        {messages.map((msg, i) => {
          const isBm = bookmarkedMessageIds.has(msg.id)
          if (msg.role === 'user') {
            return (
              <div key={msg.id}>
                <div id={`msg-${msg.id}`} />
                <UserBubble
                  content={msg.content}
                  attachments={msg.attachments}
                  visionDescriptionsUsed={msg.vision_descriptions_used}
                  liveVisionDescriptions={liveDescriptionsForMessage(msg.id)}
                  onEdit={(newContent) => onEdit(msg.id, newContent)}
                  isEditable={!isStreaming && !msg.id.startsWith('optimistic-')}
                  isBookmarked={isBm}
                  onBookmark={() => onBookmark(msg.id)}
                />
              </div>
            )
          }
          if (msg.role === 'assistant') {
            return (
              <div key={msg.id}>
                <div id={`msg-${msg.id}`} />
                {msg.web_search_context && msg.web_search_context.length > 0 && (
                  <WebSearchPills items={msg.web_search_context} />
                )}
                {msg.knowledge_context && msg.knowledge_context.length > 0 && (
                  <KnowledgePills items={msg.knowledge_context} />
                )}
                <AssistantMessage content={msg.content} thinking={msg.thinking}
                  isStreaming={false} accentColour={accentColour} highlighter={highlighter}
                  isBookmarked={isBm} onBookmark={() => onBookmark(msg.id)}
                  canRegenerate={canRegenerate && i === lastAssistantIdx} onRegenerate={onRegenerate} />
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
            {activeToolCalls.filter((tc) => tc.status === 'done' && (tc.toolName === 'create_artefact' || tc.toolName === 'update_artefact')).map((tc) => (
              <ArtefactCard
                key={tc.id}
                handle={(tc.arguments.handle as string) ?? ''}
                title={(tc.arguments.title as string) ?? (tc.arguments.handle as string) ?? ''}
                artefactType={(tc.arguments.type as string) ?? 'code'}
                isUpdate={tc.toolName === 'update_artefact'}
                sessionId={sessionId ?? ''}
              />
            ))}
            {streamingWebSearchContext.length > 0 && (
              <WebSearchPills items={streamingWebSearchContext} />
            )}
            {streamingKnowledgeContext.length > 0 && (
              <KnowledgePills items={streamingKnowledgeContext} />
            )}
            {(streamingThinking || streamingContent) ? (
              <AssistantMessage content={streamingContent} thinking={streamingThinking || null}
                isStreaming={true} accentColour={accentColour} highlighter={highlighter} />
            ) : (
              <StreamingIndicator accentColour={accentColour} />
            )}
          </div>
        )}

        {showStandaloneRegenerate && (
          <div className="flex justify-center py-2">
            <button
              type="button"
              onClick={onRegenerate}
              className="px-3 py-1 text-sm rounded-md border border-white/10 hover:bg-white/5 transition text-white/70 hover:text-white"
            >
              Generate response
            </button>
          </div>
        )}

        {/* Bottom anchor — scroll target */}
        <div ref={bottomRef} />
      </div>

      </div>

      {/* Scroll-to-bottom button — centred above input */}
      {showScrollButton && (
        <button type="button" onClick={onScrollToBottom}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-elevated text-white/40 shadow-lg transition-colors hover:bg-white/10 hover:text-white/60"
          title="Scroll to bottom">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 2V12M7 12L3 8M7 12L11 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  )
}
