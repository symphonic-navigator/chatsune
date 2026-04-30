import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import ReactMarkdown from 'react-markdown'
import { buildRehypePlugins, createMarkdownComponents, remarkPlugins, preprocessMath } from './markdownComponents'
import { ThinkingBubble } from './ThinkingBubble'
import { StatsLine } from './StatsLine'
import { ReadAloudButton } from '../voice/components/ReadAloudButton'
import { ResponseTagBuffer, type PendingEffect } from '../integrations/responseTagProcessor'
import { useIntegrationsStore } from '../integrations/store'
import { useChatStore } from '../../core/store/chatStore'
import { getActiveGroup, subscribeActiveGroup } from './responseTaskGroup'
import type { Highlighter } from 'shiki'
import type { PersonaDto } from '../../core/types/persona'

const REFUSAL_FALLBACK_TEXT = 'The model declined this request.'

// useSyncExternalStore plumbing for the active-Group registry. Pattern
// mirrors usePhase: snapshot is `<groupId>:<groupState>` so React's
// Object.is identity check reacts to state-only changes; the actual Group
// reference (and its mutated renderedPillsMap) is still read live below.
//
// The registry's listener carries the current Group as its argument, but
// useSyncExternalStore expects a no-arg listener. The tiny adaptor below
// matches the pattern in `voice/usePhase.ts` for consistency — we use the
// same shape everywhere we subscribe to the active-Group registry from
// React.
function subscribeActiveGroupForRsx(onStoreChange: () => void): () => void {
  return subscribeActiveGroup(() => onStoreChange())
}
function activeGroupSnapshot(): string {
  const g = getActiveGroup()
  return g === null ? 'none' : `${g.id}:${g.state}`
}
function serverSnapshot(): string {
  return 'none'
}

interface AssistantMessageProps {
  content: string; thinking: string | null; isStreaming: boolean;
  accentColour: string; highlighter: Highlighter | null;
  isBookmarked?: boolean; onBookmark?: () => void;
  canRegenerate?: boolean; onRegenerate?: () => void;
  status?: 'completed' | 'aborted' | 'refused';
  refusalText?: string | null;
  timeToFirstTokenMs?: number | null;
  tokensPerSecond?: number | null;
  generationDurationMs?: number | null;
  outputTokens?: number | null;
  providerName?: string | null;
  modelName?: string | null;
  sttEnabled?: boolean;
  messageId?: string;
  persona?: PersonaDto | null;
}

/**
 * Custom equality for AssistantMessage's React.memo wrapper.
 *
 * Deliberately ignores the function props (`onBookmark`, `onRegenerate`).
 * MessageList passes fresh inline closures for these every render; including
 * them would defeat memoisation entirely and keep re-running ReactMarkdown /
 * remark / rehype / Shiki for every historical message on every streaming
 * token. The closures only capture `messageId` from the parent scope, so as
 * long as that id is unchanged the callbacks are behaviourally equivalent.
 */
function areEqual(prev: AssistantMessageProps, next: AssistantMessageProps): boolean {
  return (
    prev.content === next.content &&
    prev.thinking === next.thinking &&
    prev.isStreaming === next.isStreaming &&
    prev.accentColour === next.accentColour &&
    prev.highlighter === next.highlighter &&
    prev.isBookmarked === next.isBookmarked &&
    prev.canRegenerate === next.canRegenerate &&
    prev.status === next.status &&
    prev.refusalText === next.refusalText &&
    prev.timeToFirstTokenMs === next.timeToFirstTokenMs &&
    prev.tokensPerSecond === next.tokensPerSecond &&
    prev.generationDurationMs === next.generationDurationMs &&
    prev.outputTokens === next.outputTokens &&
    prev.providerName === next.providerName &&
    prev.modelName === next.modelName &&
    prev.sttEnabled === next.sttEnabled &&
    prev.messageId === next.messageId &&
    prev.persona === next.persona
  )
}

function AssistantMessageBase({ content, thinking, isStreaming, accentColour, highlighter, isBookmarked, onBookmark, canRegenerate, onRegenerate, status = 'completed', refusalText, timeToFirstTokenMs, tokensPerSecond, generationDurationMs, outputTokens, providerName, modelName, messageId, persona }: AssistantMessageProps) {
  const effectiveContent = (() => {
    if (content) return content
    if (refusalText && status === 'refused') return refusalText
    if (status === 'refused') return REFUSAL_FALLBACK_TEXT
    return ''
  })()

  const [copied, setCopied] = useState(false)
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
  }, [])

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(effectiveContent)
    setCopied(true)
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
    copyTimeoutRef.current = setTimeout(() => setCopied(false), 1500)
  }, [effectiveContent])

  const components = useMemo(() => createMarkdownComponents(highlighter), [highlighter])

  // Live-stream pill resolution: while streaming, the active Group's
  // renderedPillsMap is mutated (Map.set) by ResponseTagBuffer.handleTag every
  // time a tag is detected. Mutating a Map in place does NOT trigger React via
  // Object.is, so we rely on two indirect re-render triggers to keep the
  // rendered output in sync with the map:
  //  - The chat store's appendStreamingContent fires for every content delta,
  //    which re-renders this component and reads the (already-mutated) map
  //    live below. This is the path that actually picks up new map entries.
  //  - useSyncExternalStore on subscribeActiveGroup catches Group identity /
  //    state changes (start, cancel, end) so we re-pick up the right map
  //    after a Group transition — the snapshot string only encodes
  //    `<groupId>:<groupState>` and does NOT change when the map gains an
  //    entry.
  // We deliberately do NOT bump a per-mutation counter — the chat-store
  // re-render covers map writes for the streaming bubble, so an additional
  // version field would only be redundant work.
  useSyncExternalStore(
    subscribeActiveGroupForRsx,
    activeGroupSnapshot,
    serverSnapshot,
  )
  const liveStreamPillContents = isStreaming
    ? (getActiveGroup()?.renderedPillsMap ?? null)
    : null

  // Cached pill map for this message id, populated by `finishStreaming`
  // from the active Group's `renderedPillsMap`. This survives the live →
  // persisted transition where the message's `content` already holds
  // placeholders (no raw tags), so the persisted-render buffer alone would
  // produce an empty pill map and the rehype plugin would strip the
  // placeholders. Empty / undefined for messages loaded from the backend
  // (F5, history-load) — those carry raw tags so the persisted-render path
  // reconstructs the map by re-parsing.
  const cachedPillContents = useChatStore((s) =>
    messageId ? s.messagePillContents[messageId] : undefined,
  )

  // Stable signature of the integration definitions that declare response
  // tag support. Used as a dep of the persisted-render memo below so that
  // when the integrations store hydrates AFTER chat history has loaded
  // (e.g. fresh page reload with a slightly later WS hello roundtrip), the
  // persisted-render buffer is rebuilt with the now-known tag prefixes —
  // otherwise old `<lovense ...>` tags would render as raw text and never
  // recompute. Sorting the ids keeps the signature insensitive to incidental
  // re-orderings of the definitions array.
  const tagPrefixSignature = useIntegrationsStore((s) =>
    s.definitions
      .filter((d) => d.has_response_tags)
      .map((d) => d.id)
      .sort()
      .join(','),
  )

  // Persisted-message pill resolution: when this message is no longer
  // streaming AND it has a messageId, run the content once through a
  // ResponseTagBuffer with side effects suppressed to capture pill content
  // for every `<integration ...>` tag in the persisted text. Memoised on
  // (messageId, content) so the heavy regex / plugin lookup only runs when
  // the message identity or text actually changes; scrolling the chat does
  // not re-fire it.
  const persistedRender = useMemo(() => {
    if (isStreaming) return null
    if (!effectiveContent) return null
    const pending = new Map<string, PendingEffect>()
    const pills = new Map<string, string>()
    const buffer = new ResponseTagBuffer(
      () => undefined,
      'text_only',
      pending,
      () => undefined,
      pills,
      { runSideEffects: false },
    )
    const sanitised = buffer.process(effectiveContent)
    // Intentionally NOT calling buffer.flush(): flush emits any residual
    // parked triggers, which we must not do at render time. The pending
    // map (which we discard) is in any case empty for `text_only` source
    // because every successful tag immediately fired its (no-op) emitter.
    return { renderedText: sanitised, pillContents: pills }
    // messageId is part of the dep list so a swap from optimistic →
    // backend id refreshes the cached render. tagPrefixSignature covers the
    // hydration race where chat history loads before the integrations store
    // has populated its definitions: when the signature flips from '' (or
    // any older value) to one that includes the relevant prefix, we rebuild
    // the buffer so persisted tags are no longer rendered as raw text.
  }, [isStreaming, effectiveContent, messageId, tagPrefixSignature])

  // Pick which pill map feeds the rehype plugin. Live-stream branch reads
  // the active Group's mirror (mutated as tokens arrive); persisted branch
  // reads the per-message memoised map.
  const pillContents = isStreaming
    ? liveStreamPillContents ?? undefined
    : (cachedPillContents ?? persistedRender?.pillContents)
  const rehypePluginsForRender = useMemo(
    () => buildRehypePlugins({ pillContents }),
    [pillContents],
  )

  // For persisted messages we feed the buffer's sanitised output (raw tags
  // already replaced with placeholders); for live streams the chat store
  // already holds the pre-sanitised content so we render it directly.
  const renderText = isStreaming
    ? effectiveContent
    : (persistedRender?.renderedText ?? effectiveContent)

  return (
    <div className="animate-message-entrance">
      {thinking && (
        <ThinkingBubble content={thinking} isStreaming={isStreaming && !content} accentColour={accentColour} />
      )}
      <div className="max-w-[92%] lg:max-w-[85%] min-w-0 break-words [overflow-wrap:anywhere]">
        <div className="chat-text chat-prose text-white/80">
          <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePluginsForRender} components={components}>
            {preprocessMath(renderText)}
          </ReactMarkdown>
        </div>
        {status === 'aborted' && !isStreaming && (
          <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-400/30 bg-amber-400/5 px-3 py-2">
            <svg
              width="14" height="14" viewBox="0 0 14 14" fill="none"
              className="text-amber-400 mt-0.5 shrink-0"
              aria-hidden="true"
            >
              <path
                d="M7 1.5L13 12.5H1L7 1.5Z"
                stroke="currentColor" strokeWidth="1.2"
                strokeLinecap="round" strokeLinejoin="round"
              />
              <path
                d="M7 5.5V8.5M7 10.5V10.51"
                stroke="currentColor" strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
            <div className="text-[11px] leading-snug text-amber-200/90">
              This response was interrupted and may be incomplete.
              Click <strong>Regenerate</strong> to produce a fresh response.
            </div>
          </div>
        )}
        {status === 'refused' && !isStreaming && (
          <div className="mt-2 flex items-start gap-2 rounded-md border border-red-400/40 bg-red-500/5 px-3 py-2">
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              className="text-red-400 mt-0.5 shrink-0"
              aria-hidden="true"
            >
              <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
              <path
                d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
            <div className="text-[11px] leading-snug text-red-200/90">
              The model declined this request. Click <strong>Regenerate</strong> to try again.
            </div>
          </div>
        )}
        {!isStreaming && effectiveContent && (
          <>
            <div className="mt-2.5 flex gap-3 border-t border-white/6 pt-2">
              <button type="button" onClick={handleCopy}
                className="flex items-center gap-1 text-[11px] text-white/25 transition-colors hover:text-white/50"
                title={copied ? 'Copied!' : 'Copy message'}>
                {copied ? (
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                    <path d="M3 7L6 10L11 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                    <rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
                    <path d="M10 4V2.5C10 1.5 9.55 1.5 9 1.5H2.5C1.95 1.5 1.5 1.95 1.5 2.5V9C1.5 9.55 1.95 10 2.5 10H4" stroke="currentColor" strokeWidth="1.2" />
                  </svg>
                )}
                {copied ? 'Copied' : 'Copy'}
              </button>
              {onBookmark && (
                <button type="button" onClick={onBookmark}
                  className={`flex items-center gap-1 text-[11px] transition-colors ${isBookmarked ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
                  title={isBookmarked ? 'Bookmarked' : 'Bookmark'}>
                  <svg width="13" height="13" viewBox="0 0 14 14" fill={isBookmarked ? 'currentColor' : 'none'}>
                    <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                  </svg>
                  {isBookmarked ? 'Bookmarked' : 'Bookmark'}
                </button>
              )}
              {messageId && (
                <ReadAloudButton
                  messageId={messageId}
                  content={effectiveContent}
                  persona={persona}
                />
              )}
              {canRegenerate && onRegenerate && (
                <button type="button" onClick={onRegenerate}
                  className="flex items-center gap-1 text-[11px] text-white/25 transition-colors hover:text-white/50"
                  title="Regenerate response">
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                    <path d="M1.5 7C1.5 4 4 1.5 7 1.5C10 1.5 12.5 4 12.5 7C12.5 10 10 12.5 7 12.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                    <path d="M1.5 7L3.5 5M1.5 7L3.5 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Regenerate
                </button>
              )}
            </div>
            <StatsLine
              timeToFirstTokenMs={timeToFirstTokenMs}
              tokensPerSecond={tokensPerSecond}
              generationDurationMs={generationDurationMs}
              outputTokens={outputTokens}
              providerName={providerName}
              modelName={modelName}
            />
          </>
        )}
      </div>
    </div>
  )
}

export const AssistantMessage = memo(AssistantMessageBase, areEqual)
