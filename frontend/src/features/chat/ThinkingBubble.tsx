import { useCallback, useEffect, useRef, useState } from 'react'

interface ThinkingBubbleProps {
  content: string
  isStreaming: boolean
  accentColour: string
}

export function ThinkingBubble({ content, isStreaming, accentColour }: ThinkingBubbleProps) {
  const [isExpanded, setIsExpanded] = useState(true)
  const contentRef = useRef<HTMLDivElement>(null)
  const [measuredHeight, setMeasuredHeight] = useState<number>(0)

  useEffect(() => {
    if (isStreaming) setIsExpanded(true)
  }, [isStreaming])

  useEffect(() => {
    if (!contentRef.current) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setMeasuredHeight(entry.contentRect.height)
      }
    })
    observer.observe(contentRef.current)
    return () => observer.disconnect()
  }, [])

  const toggle = useCallback(() => {
    if (!isStreaming) setIsExpanded((prev) => !prev)
  }, [isStreaming])

  if (!content && !isStreaming) return null

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={toggle}
        className="flex items-center gap-2 rounded-full px-3 py-1 text-[12px] transition-colors"
        style={{
          background: `${accentColour}10`,
          border: `1px solid ${accentColour}20`,
          color: `${accentColour}AA`,
        }}
      >
        <span className="text-[10px]">{isExpanded ? '\u25BC' : '\u25B6'}</span>
        <span>Thinking</span>
        {isStreaming && (
          <span data-testid="thinking-dots" className="flex items-center gap-1 ml-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="inline-block h-1.5 w-1.5 rounded-full animate-think-pulse"
                style={{ backgroundColor: accentColour, animationDelay: `${i * 0.3}s` }}
              />
            ))}
          </span>
        )}
      </button>
      <div
        data-testid="thinking-content"
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{ maxHeight: isExpanded ? `${measuredHeight + 16}px` : '0px' }}
      >
        <div
          ref={contentRef}
          className="thinking-text mt-1 rounded-lg px-3 py-2 text-[13px] italic leading-relaxed"
          style={{
            background: `${accentColour}08`,
            borderLeft: `3px solid ${accentColour}30`,
            color: 'rgba(255, 255, 255, 0.5)',
          }}
        >
          {content}
        </div>
      </div>
    </div>
  )
}
