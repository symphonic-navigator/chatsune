import { useCallback, useEffect, useRef, useState } from 'react'

const SCROLL_THRESHOLD = 80

export function useAutoScroll(isStreaming: boolean) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const isNearBottomRef = useRef(true)

  const checkNearBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
    isNearBottomRef.current = nearBottom
    setShowScrollButton(!nearBottom)
  }, [])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    el.addEventListener('scroll', checkNearBottom, { passive: true })
    return () => el.removeEventListener('scroll', checkNearBottom)
  }, [checkNearBottom])

  useEffect(() => {
    if (!isStreaming) return
    const interval = setInterval(() => {
      if (isNearBottomRef.current && containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight
      }
    }, 100)
    return () => clearInterval(interval)
  }, [isStreaming])

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    // Instant snap — smooth scrolling can undershoot when content height
    // changes during the animation (fonts loading, syntax highlighting).
    // Double-rAF ensures layout is complete before measuring scrollHeight.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight
      })
    })
  }, [])

  return { containerRef, showScrollButton, scrollToBottom }
}
