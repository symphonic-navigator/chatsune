import { useCallback, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createMarkdownComponents } from './markdownComponents'
import { ThinkingBubble } from './ThinkingBubble'
import type { Highlighter } from 'shiki'

interface AssistantMessageProps {
  content: string; thinking: string | null; isStreaming: boolean;
  accentColour: string; highlighter: Highlighter | null;
  thinkingDefaultExpanded?: boolean; onThinkingToggle?: (expanded: boolean) => void;
  isBookmarked?: boolean; onBookmark?: () => void;
}

export function AssistantMessage({ content, thinking, isStreaming, accentColour, highlighter, thinkingDefaultExpanded, onThinkingToggle, isBookmarked, onBookmark }: AssistantMessageProps) {
  const [copied, setCopied] = useState(false)
  const [isHovered, setIsHovered] = useState(false)

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [content])

  const components = createMarkdownComponents(highlighter)

  return (
    <div className="group animate-message-entrance"
      onMouseEnter={() => setIsHovered(true)} onMouseLeave={() => setIsHovered(false)}>
      {thinking && (
        <ThinkingBubble content={thinking} isStreaming={isStreaming && !content} accentColour={accentColour}
          defaultExpanded={thinkingDefaultExpanded} onToggle={onThinkingToggle} />
      )}
      <div className="relative max-w-[85%]">
        {isHovered && !isStreaming && content && (
          <div className="absolute -right-8 top-1 flex flex-col gap-1">
            <button type="button" onClick={handleCopy}
              className="rounded p-1 text-white/20 transition-colors hover:text-white/50"
              title={copied ? 'Copied!' : 'Copy message'}>
              {copied ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M3 7L6 10L11 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M10 4V2.5C10 1.5 9.55 1.5 9 1.5H2.5C1.95 1.5 1.5 1.95 1.5 2.5V9C1.5 9.55 1.95 10 2.5 10H4" stroke="currentColor" strokeWidth="1.2" />
                </svg>
              )}
            </button>
            {onBookmark && (
              <button type="button" onClick={onBookmark}
                className={`rounded p-1 transition-colors ${isBookmarked ? 'text-gold' : 'text-white/20 hover:text-white/50'}`}
                title={isBookmarked ? 'Bookmarked' : 'Bookmark'}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill={isBookmarked ? 'currentColor' : 'none'}>
                  <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        )}
        <div className="chat-text chat-prose text-white/80">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
