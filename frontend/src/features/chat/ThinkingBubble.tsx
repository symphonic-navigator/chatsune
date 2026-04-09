import { useCallback, useEffect, useRef, useState } from 'react'

interface ThinkingBubbleProps {
  content: string
  isStreaming: boolean
  accentColour: string
}

/**
 * Thinking bubble with an explicit open/close state machine:
 *
 *   - While the model is actively streaming thinking tokens
 *     (``isStreaming === true``), the bubble is forced open so the
 *     user can see the thought process as it arrives.
 *   - The moment the model switches to producing response content
 *     (``isStreaming`` flips to false), the bubble auto-collapses.
 *   - Once the stream is fully over, the persisted message still
 *     renders the bubble closed by default.
 *   - The user can override either state at any time via the
 *     toggle button. A manual override sticks until the next
 *     thinking burst starts (next ``isStreaming === true``
 *     transition), which resets the override back to the automatic
 *     behaviour.
 */
export function ThinkingBubble({ content, isStreaming, accentColour }: ThinkingBubbleProps) {
  const [isExpanded, setIsExpanded] = useState(isStreaming)
  const userToggledRef = useRef(false)
  const contentRef = useRef<HTMLDivElement>(null)
  const [measuredHeight, setMeasuredHeight] = useState<number>(0)

  useEffect(() => {
    if (isStreaming) {
      // New thinking burst — reset any previous manual override and
      // open the bubble so the user sees the tokens as they arrive.
      userToggledRef.current = false
      setIsExpanded(true)
    } else if (!userToggledRef.current) {
      // Model stopped thinking (either it is now producing content or
      // the stream is done). Auto-collapse unless the user has
      // explicitly chosen to keep it open.
      setIsExpanded(false)
    }
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
    setIsExpanded((prev) => {
      userToggledRef.current = true
      return !prev
    })
  }, [])

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
        <svg width="8" height="8" viewBox="0 0 8 8" fill="none"
          style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>
          <path d="M2 1L6 4L2 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
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
