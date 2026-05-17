import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  ChatMessageDto,
  CompactionCheckpoint,
  KnowledgeContextItem,
  PtiOverflow,
  TimelineEntry,
  TimelineEntryKnowledgeSearch,
  ToolCallRef,
} from '../../core/api/chat'
import { type LiveVisionDescription, useChatStore } from '../../core/store/chatStore'
import type { Highlighter } from 'shiki'
import type { PersonaDto } from '../../core/types/persona'
import { useReportBounds } from '../voice/infrastructure/useReportBounds'
import { UserBubble } from './UserBubble'
import { AssistantMessage } from './AssistantMessage'
import { StreamingIndicator } from './StreamingIndicator'
import { WebSearchPills } from './WebSearchPills'
import { KnowledgePills } from './KnowledgePills'
import { ToolCallPill } from './ToolCallPill'
import type { StreamingToolCall } from '../../core/store/chatStore'
import { ArtefactCard } from '../artefact/ArtefactCard'
import { InlineImageBlock } from '../images/chat/InlineImageBlock'
import { CompactedMarkerPill } from './compaction/CompactedMarkerPill'
import { CompactedSnapshotDrawer } from './compaction/CompactedSnapshotDrawer'

interface MessageListProps {
  sessionId: string | null
  messages: ChatMessageDto[]
  streamingContent: string
  streamingThinking: string
  streamingEvents: TimelineEntry[]
  streamingToolCalls: Map<string, StreamingToolCall>
  isWaitingForResponse: boolean
  isStreaming: boolean
  /**
   * Per-session streaming-state slices. Threaded as props from ChatView
   * because the chatStore now keys these by sessionId — reading them
   * directly via useChatStore selectors here would lose the active-session
   * scoping that the parent already has.
   */
  visionDescriptions: Record<string, LiveVisionDescription>
  streamingCorrelationId: string | null
  streamingSlow: boolean
  accentColour: string
  highlighter: Highlighter | null
  containerRef: (node: HTMLDivElement | null) => void
  bottomRef: React.RefObject<HTMLDivElement | null>
  showScrollButton: boolean
  onScrollToBottom: () => void
  onEdit: (messageId: string, content: string) => void
  /**
   * Triggered by the action-bar regenerate button on assistant messages
   * (and the standalone "Generate response" CTA at the foot of the list).
   *
   * The optional ``messageId`` and ``isLastAssistant`` arguments tell
   * ChatView whether to run an in-place regenerate or to fork into a new
   * branch first ("Branch & Regenerate" label, spec §6.1). Existing call
   * sites that pass no arguments keep the legacy in-place behaviour for
   * the trailing-CTA path.
   */
  onRegenerate: (args?: { messageId?: string; isLastAssistant?: boolean }) => void
  /**
   * Triggered by the action-bar Branch button on assistant messages.
   * Fires with the assistant message id that should become the
   * fork-point. ChatView opens ``BranchNameDialog`` and routes the
   * confirmation through ``chatApi.branchSession``. See
   * ``devdocs/specs/2026-05-17-branching-design.md`` §6.1.
   */
  onBranch?: (messageId: string) => void
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

/**
 * Subtitle rendered beneath every timeline entry whose ``cloned_from_branch``
 * flag is set. The flag is stamped by the backend at branch-creation time on
 * the cloned message's events array; renderers are otherwise unchanged.
 * See ``devdocs/specs/2026-05-17-branching-design.md`` §4.4 / §6.5.
 */
function ClonedFromBranchSubtitle() {
  return (
    <div
      data-testid="cloned-from-branch-subtitle"
      className="-mt-1 mb-2 text-[10px] italic leading-snug text-white/35"
    >
      Cloned from parent — not re-executed
    </div>
  )
}

function renderTimelineEntry(
  entry: TimelineEntry,
  sessionId: string,
  keyPrefix: string,
): React.ReactNode {
  const k = `${keyPrefix}-${entry.seq}-${entry.kind}`
  // Stamped on cloned timeline entries when a branch is created. The flag
  // is per-entry rather than per-message so a single assistant doc may
  // contain a mix of cloned and live events after future regenerate flows
  // (the spec defers that — for now every entry on a cloned message is
  // flagged uniformly).
  const isCloned = entry.cloned_from_branch === true
  const subtitle = isCloned ? <ClonedFromBranchSubtitle /> : null
  switch (entry.kind) {
    case 'knowledge_search':
      return (
        <div key={k}>
          <KnowledgePills
            items={entry.items}
            overflow={entry._overflow ?? null}
          />
          {subtitle}
        </div>
      )
    case 'web_search':
      return (
        <div key={k}>
          <WebSearchPills items={entry.items} />
          {subtitle}
        </div>
      )
    case 'tool_call': {
      const ref: ToolCallRef = {
        tool_call_id: entry.tool_call_id,
        tool_name: entry.tool_name,
        arguments: entry.arguments,
        success: entry.success,
        moderated_count: entry.moderated_count,
        result_content: entry.result_content ?? null,
      }
      return (
        <div key={k}>
          <ToolCallPill phase={{ kind: 'completed', ref }} />
          {subtitle}
        </div>
      )
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
          {subtitle}
        </div>
      )
    case 'image':
      return (
        <div key={k}>
          <InlineImageBlock
            refs={entry.refs}
            moderatedCount={entry.moderated_count ?? 0}
          />
          {subtitle}
        </div>
      )
  }
}

export function MessageList({
  sessionId, messages, streamingContent, streamingThinking, streamingEvents, streamingToolCalls,
  isWaitingForResponse, isStreaming, accentColour, highlighter,
  visionDescriptions, streamingCorrelationId, streamingSlow,
  containerRef, bottomRef, showScrollButton, onScrollToBottom, onEdit, onRegenerate, onBranch, bookmarkedMessageIds, onBookmark, sttEnabled, persona,
}: MessageListProps) {
  // Compact-and-continue checkpoints for the active session, hydrated
  // from the messages bundle on session-switch and extended on
  // ``chat.compaction.completed`` WS events. Indexed by the tail-start
  // message id so the renderer can drop a `Compacted` marker BEFORE the
  // first message of the tail range — visually separating the source
  // (now condensed into the briefing) from the verbatim tail.
  const compactionCheckpoints = useChatStore((s) => s.compactionCheckpoints)
  const checkpointByTailStart = useMemo(() => {
    const map = new Map<string, CompactionCheckpoint>()
    for (const cp of compactionCheckpoints) {
      map.set(cp.tail_start_message_id, cp)
    }
    return map
  }, [compactionCheckpoints])
  // The earliest tail-start across all checkpoints — used to grey out
  // the edit button on source-range messages (the backend already
  // rejects edits before this cutoff with ``edit_before_compact``;
  // disabling the UI keeps the rejection from being a surprise).
  const earliestTailStartIdx = useMemo(() => {
    if (compactionCheckpoints.length === 0) return -1
    const tailStartIds = new Set(
      compactionCheckpoints.map((cp) => cp.tail_start_message_id),
    )
    return messages.findIndex((m) => tailStartIds.has(m.id))
  }, [compactionCheckpoints, messages])
  // ``openCheckpoint`` drives the read-only snapshot drawer mounted at
  // the root of this component. ``null`` keeps the drawer unmounted.
  const [openCheckpoint, setOpenCheckpoint] = useState<CompactionCheckpoint | null>(null)

  const lastAssistantIdx = messages.findLastIndex((m) => m.role === 'assistant')
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null
  const canRegenerate =
    !isStreaming &&
    lastMsg !== null &&
    (lastMsg.role === 'assistant' || lastMsg.role === 'user')
  const showStandaloneRegenerate = canRegenerate && lastMsg !== null && lastMsg.role === 'user'
  // Non-last assistant messages get a "Branch & Regenerate" regenerate button
  // (forks first, then runs inference on the fork) plus a standalone Branch
  // button. Only render the regenerate row at all when not streaming.
  const canAssistantAction = !isStreaming && onBranch !== undefined

  // Renamed locally to keep the rest of the body unchanged.
  const correlationId = streamingCorrelationId

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
          // Compact-and-continue: drop a `Compacted` marker BEFORE the
          // tail-start message so the divider visually separates the
          // source range (now folded into the briefing) from the verbatim
          // tail. ``checkpointByTailStart`` is the indexed view of the
          // session's checkpoint list — see hydration at the top of the
          // component.
          const checkpointHere = checkpointByTailStart.get(msg.id) ?? null
          const marker = checkpointHere ? (
            <CompactedMarkerPill
              key={`compacted-${checkpointHere.id}`}
              checkpoint={checkpointHere}
              onOpen={() => setOpenCheckpoint(checkpointHere)}
            />
          ) : null
          // Edits to messages before the earliest tail-start are rejected
          // by the backend with ``edit_before_compact``. Grey out the
          // pencil button up-front so the user doesn't hit a backend
          // rejection.
          const isBeforeCompact =
            earliestTailStartIdx > 0 && i < earliestTailStartIdx
          if (msg.role === 'user') {
            return (
              <div key={msg.id}>
                {marker}
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
                  // forbidding mid-stream edits. Messages before the
                  // compaction tail-start are also un-editable — the
                  // backend would reject the request anyway.
                  isEditable={!msg.is_optimistic && !isBeforeCompact}
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
                {marker}
                <div id={`msg-${msg.id}`} />
                {events.map((entry) =>
                  renderTimelineEntry(entry, sessionId ?? '', msg.id),
                )}
                <AssistantMessage content={msg.content} thinking={msg.thinking}
                  isStreaming={false} accentColour={accentColour} highlighter={highlighter}
                  isBookmarked={isBm} onBookmark={onBookmark ? () => onBookmark(msg.id) : undefined}
                  canRegenerate={
                    // Regenerate button visible on:
                    //   - the last assistant (in-place regenerate as before), or
                    //   - any earlier assistant when branching is wired in
                    //     (label becomes "Branch & Regenerate" via the
                    //     ``isLastAssistant === false`` branch in AssistantMessage).
                    i === lastAssistantIdx
                      ? canRegenerate
                      : canAssistantAction
                  }
                  onRegenerate={
                    () => onRegenerate({
                      messageId: msg.id,
                      isLastAssistant: i === lastAssistantIdx,
                    })
                  }
                  isLastAssistant={i === lastAssistantIdx}
                  onBranch={onBranch && !isStreaming ? () => onBranch(msg.id) : undefined}
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
            {Array.from(streamingToolCalls.values()).map((tc) => (
              <ToolCallPill
                key={tc.toolCallId}
                phase={
                  tc.phase === 'streaming'
                    ? {
                        kind: 'streaming',
                        toolName: tc.toolName,
                        charCount: tc.charCount,
                        argsBuffer: tc.argsBuffer,
                        toolCallId: tc.toolCallId,
                      }
                    : {
                        kind: 'executing',
                        toolName: tc.toolName ?? 'tool',
                        arguments: tc.parsedArguments ?? {},
                        toolCallId: tc.toolCallId,
                      }
                }
              />
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
              onClick={() => onRegenerate()}
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

      {/* Compaction snapshot drawer — opened by clicking a CompactedMarkerPill.
          Renders nothing while ``openCheckpoint`` is null. Mounted at the
          MessageList root so the open state stays scoped to the message-list
          lifetime. */}
      <CompactedSnapshotDrawer
        checkpoint={openCheckpoint}
        onClose={() => setOpenCheckpoint(null)}
      />

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
