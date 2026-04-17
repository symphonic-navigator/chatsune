import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { createMarkdownComponents, remarkPlugins, rehypePlugins, preprocessMath } from './markdownComponents'
import { ThinkingBubble } from './ThinkingBubble'
import { StatsLine } from './StatsLine'
import { ReadAloudButton } from '../voice/components/ReadAloudButton'
import type { Highlighter } from 'shiki'
import type { PersonaDto } from '../../core/types/persona'

const REFUSAL_FALLBACK_TEXT = 'The model declined this request.'

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

export function AssistantMessage({ content, thinking, isStreaming, accentColour, highlighter, isBookmarked, onBookmark, canRegenerate, onRegenerate, status = 'completed', refusalText, timeToFirstTokenMs, tokensPerSecond, generationDurationMs, outputTokens, providerName, modelName, messageId, persona }: AssistantMessageProps) {
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

  return (
    <div className="animate-message-entrance">
      {thinking && (
        <ThinkingBubble content={thinking} isStreaming={isStreaming && !content} accentColour={accentColour} />
      )}
      <div className="max-w-[92%] lg:max-w-[85%] min-w-0 break-words [overflow-wrap:anywhere]">
        <div className="chat-text chat-prose text-white/80">
          <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>
            {preprocessMath(effectiveContent)}
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
                <ReadAloudButton messageId={messageId} content={effectiveContent} persona={persona} />
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
