import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  ChatMessageDto,
  KnowledgeContextItem,
  PtiOverflow,
  TimelineEntry,
  TimelineEntryKnowledgeSearch,
  ToolCallRef,
} from '../../core/api/chat'
import { useChatStore, type LiveVisionDescription } from '../../core/store/chatStore'
import type { Highlighter } from 'shiki'
import type { PersonaDto } from '../../core/types/persona'
import { useReportBounds } from '../voice/infrastructure/useReportBounds'
import { UserBubble } from './UserBubble'
import { AssistantMessage } from './AssistantMessage'
import { StreamingIndicator } from './StreamingIndicator'
import { WebSearchPills } from './WebSearchPills'
import { KnowledgePills } from './KnowledgePills'
import { ToolCallPills } from './ToolCallPills'
import { ToolCallActivity } from './ToolCallActivity'
import { ArtefactCard } from '../artefact/ArtefactCard'
import { InlineImageBlock } from '../images/chat/InlineImageBlock'

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
  streamingEvents: TimelineEntry[]
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
  onBookmark?: (messageId: string) => void
  sttEnabled?: boolean
  persona?: PersonaDto | null
}

/**
 * Fold the preceding user message's PTI items into the assistant message's
 * first `knowledge_search` entry — render-only, never mutates the store.
 *
 * Rules per spec:
 *   1. If there is at least one `knowledge_search` entry, prepend `ptiItems`
 *      to its `items` and attach `_overflow = ptiOverflow`.
 *   2. Else if `ptiItems` is non-empty or `ptiOverflow` is set, prepend a
 *      synthetic entry at index 0 with `seq = -1`.
 *   3. Else return `rawEvents` unchanged.
 */
export function mergePtiIntoFirstKnowledgeEntry(
  rawEvents: TimelineEntry[],
  ptiItems: KnowledgeContextItem[],
  ptiOverflow: PtiOverflow | null,
): TimelineEntry[] {
  const idx = rawEvents.findIndex((e) => e.kind === 'knowledge_search')
  if (idx >= 0) {
    const existing = rawEvents[idx] as TimelineEntryKnowledgeSearch
    const merged: TimelineEntryKnowledgeSearch = {
      ...existing,
      items: [...ptiItems, ...existing.items],
      _overflow: ptiOverflow,
    }
    const next = [...rawEvents]
    next[idx] = merged
    return next
  }
  if (ptiItems.length > 0 || ptiOverflow) {
    const synthetic: TimelineEntryKnowledgeSearch = {
      kind: 'knowledge_search',
      seq: -1,
      items: ptiItems,
      _overflow: ptiOverflow,
    }
    return [synthetic, ...rawEvents]
  }
  return rawEvents
}

function renderTimelineEntry(
  entry: TimelineEntry,
  sessionId: string,
  keyPrefix: string,
): React.ReactNode {
  const k = `${keyPrefix}-${entry.seq}-${entry.kind}`
  switch (entry.kind) {
    case 'knowledge_search':
      return (
        <KnowledgePills
          key={k}
          items={entry.items}
          overflow={entry._overflow ?? null}
        />
      )
    case 'web_search':
      return <WebSearchPills key={k} items={entry.items} />
    case 'tool_call': {
      // ToolCallPills consumes the ToolCallRef shape — the timeline entry
      // already carries the same identifying fields, just re-wrapped.
      const ref: ToolCallRef = {
        tool_call_id: entry.tool_call_id,
        tool_name: entry.tool_name,
        arguments: entry.arguments,
        success: entry.success,
        moderated_count: entry.moderated_count,
      }
      return <ToolCallPills key={k} toolCalls={[ref]} />
    }
    case 'artefact':
      return (
        <div key={k} className="my-2 flex flex-col gap-2">
          <ArtefactCard
            handle={entry.ref.handle}
            title={entry.ref.title}
            artefactType={entry.ref.artefact_type}
            isUpdate={entry.ref.operation === 'update'}
            sessionId={sessionId}
          />
        </div>
      )
    case 'image':
      return (
        <InlineImageBlock
          key={k}
          refs={entry.refs}
          moderatedCount={entry.moderated_count ?? 0}
        />
      )
  }
}

export function MessageList({
  sessionId, messages, streamingContent, streamingThinking, streamingEvents, activeToolCalls,
  isWaitingForResponse, isStreaming, accentColour, highlighter,
  containerRef, bottomRef, showScrollButton, onScrollToBottom, onEdit, onRegenerate, bookmarkedMessageIds, onBookmark, sttEnabled, persona,
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
  const streamingSlow = useChatStore((s) => s.streamingSlow)

  const textColumnRef = useReportBounds<HTMLDivElement>('textColumn')

  const [slowElapsed, setSlowElapsed] = useState<number>(0)
  const slowSinceRef = useRef<number | null>(null)

  useEffect(() => {
    if (!streamingSlow) {
      slowSinceRef.current = null
      setSlowElapsed(0)
      return
    }
    slowSinceRef.current = Date.now()
    setSlowElapsed(0)
    const interval = setInterval(() => {
      if (slowSinceRef.current) {
        setSlowElapsed(Math.floor((Date.now() - slowSinceRef.current) / 1000))
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [streamingSlow])

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

  function formatElapsed(seconds: number): string {
    if (seconds < 60) return `${seconds}s`
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}m ${s}s`
  }

  // overflow-anchor: none on the scroll container alone is not enough — the
  // CSS property applies per-element and is non-inherited, so descendants can
  // still be picked as anchors. Disabling it on every descendant is what
  // actually stops the browser from rewinding scrollTop during layout passes
  // triggered by, e.g., textarea autosize hops in the prompt input.
  const scrollbarStyle = `
    .chat-scroll::-webkit-scrollbar { width: 8px; }
    .chat-scroll::-webkit-scrollbar-track { background: transparent; }
    .chat-scroll::-webkit-scrollbar-thumb { background: ${accentColour}33; border-radius: 4px; }
    .chat-scroll::-webkit-scrollbar-thumb:hover { background: ${accentColour}66; }
    .chat-scroll, .chat-scroll * { overflow-anchor: none; }
  `

  // Build the live-streaming events list once, including the PTI merge from
  // the most recent user message. Same merge applied to persisted messages
  // below — that's what keeps live and reload renders DOM-identical.
  const lastUserMsg = useMemo(() => {
    const idx = messages.findLastIndex((m) => m.role === 'user')
    return idx === -1 ? null : messages[idx]
  }, [messages])
  const liveMergedEvents = useMemo(() => {
    const ptiItems = lastUserMsg?.knowledge_context ?? []
    const ptiOverflow = lastUserMsg?.pti_overflow ?? null
    return mergePtiIntoFirstKnowledgeEntry(streamingEvents, ptiItems, ptiOverflow)
  }, [streamingEvents, lastUserMsg])

  return (
    <div className="relative flex-1">
      {/*
        `[overflow-anchor:none]` disables the browser's default scroll-anchoring.
        At stream-end the streaming block is swapped out for the persisted
        message (different DOM subtrees, different heights). With the default
        `overflow-anchor: auto` the browser adjusts `scrollTop` to keep visual
        content stable, which fires a programmatic scroll event that
        useAutoScroll's handler reads as "no longer near bottom" — flipping
        `followingRef` to false and breaking auto-follow permanently.
      */}
      <div ref={containerRef} className="chat-scroll absolute inset-0 overflow-y-auto px-3 py-6 lg:px-4 [overflow-anchor:none]">
      <style>{scrollbarStyle}</style>
      <div ref={textColumnRef} className="mx-auto flex max-w-3xl flex-col gap-4">
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
                  // Action bar visibility decoupled from streaming state: keeping
                  // it always rendered (modulo optimistic messages without a
                  // stable id) means user-bubble heights stay constant across
                  // stream start/end, so the chat doesn't visually jump when
                  // every existing user message gains/loses its action row at
                  // once. The Edit button is disabled (greyed out) while a
                  // stream is in flight to preserve the prior behaviour of
                  // forbidding mid-stream edits.
                  isEditable={!msg.id.startsWith('optimistic-')}
                  editDisabled={isStreaming}
                  isBookmarked={isBm}
                  onBookmark={onBookmark ? () => onBookmark(msg.id) : undefined}
                />
              </div>
            )
          }
          if (msg.role === 'assistant') {
            // PTI items live on the preceding user message but represent
            // context the assistant used. The render merge folds them into
            // the assistant's first knowledge_search entry so live and
            // reload paths produce the same DOM structure.
            const prev = messages[i - 1]
            const ptiItems =
              prev && prev.role === 'user' ? (prev.knowledge_context ?? []) : []
            const ptiOverflow =
              prev && prev.role === 'user' ? (prev.pti_overflow ?? null) : null
            const events = mergePtiIntoFirstKnowledgeEntry(
              msg.events ?? [],
              ptiItems,
              ptiOverflow,
            )
            return (
              <div key={msg.id}>
                <div id={`msg-${msg.id}`} />
                {events.map((entry) =>
                  renderTimelineEntry(entry, sessionId ?? '', msg.id),
                )}
                <AssistantMessage content={msg.content} thinking={msg.thinking}
                  isStreaming={false} accentColour={accentColour} highlighter={highlighter}
                  isBookmarked={isBm} onBookmark={onBookmark ? () => onBookmark(msg.id) : undefined}
                  canRegenerate={canRegenerate && i === lastAssistantIdx} onRegenerate={onRegenerate}
                  status={msg.status ?? 'completed'}
                  refusalText={msg.refusal_text ?? null}
                  timeToFirstTokenMs={msg.time_to_first_token_ms}
                  tokensPerSecond={msg.tokens_per_second}
                  generationDurationMs={msg.generation_duration_ms}
                  outputTokens={msg.usage?.output_tokens}
                  providerName={msg.provider_name}
                  modelName={msg.model_name}
                  sttEnabled={sttEnabled}
                  messageId={msg.id}
                  persona={persona} />
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
            {liveMergedEvents.map((entry) =>
              renderTimelineEntry(entry, sessionId ?? '', 'live'),
            )}
            {/*
              In-flight tool indicators are the only piece that legitimately
              differs between live and reload — by definition there are no
              running tools after reload. They are placed AFTER the events
              list and BEFORE the message body so that, when a tool
              completes, the activity indicator vanishes at the same moment
              the corresponding pill appears above it.
            */}
            {activeToolCalls.filter((tc) => tc.status === 'running').map((tc) => (
              <ToolCallActivity key={tc.id} toolName={tc.toolName} arguments={tc.arguments} />
            ))}
            {(streamingThinking || streamingContent) ? (
              <AssistantMessage content={streamingContent} thinking={streamingThinking || null}
                isStreaming={true} accentColour={accentColour} highlighter={highlighter}
                sttEnabled={sttEnabled} />
            ) : (
              <StreamingIndicator accentColour={accentColour} />
            )}
            {streamingSlow && (
              <div className="mt-1 text-[11px] italic text-white/45">
                Model still working… {slowElapsed > 0 && formatElapsed(slowElapsed)}
              </div>
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
