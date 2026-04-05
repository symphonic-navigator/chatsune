import { useCallback, useEffect, useRef, useState } from 'react'

const SCROLL_THRESHOLD = 80

export function useAutoScroll(isStreaming: boolean) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  // Track whether the user intentionally scrolled away from the bottom.
  // Reset when streaming starts or when scrollToBottom is called.
  const userScrolledUpRef = useRef(false)
  const programmaticScrollRef = useRef(false)

  const isNearBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
  }, [])

  // Scroll event handler — detect user scrolling up vs. our programmatic scroll
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let lastScrollTop = el.scrollTop

    function onScroll() {
      const el = containerRef.current
      if (!el) return

      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
      setShowScrollButton(!nearBottom)

      if (programmaticScrollRef.current) {
        // This scroll was caused by us — ignore for user-intent detection
        programmaticScrollRef.current = false
        lastScrollTop = el.scrollTop
        return
      }

      // User scrolled up intentionally
      if (el.scrollTop < lastScrollTop - 2) {
        userScrolledUpRef.current = true
      }
      // User scrolled back to bottom
      if (nearBottom) {
        userScrolledUpRef.current = false
      }
      lastScrollTop = el.scrollTop
    }

    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // Auto-scroll during streaming — runs every 80ms
  useEffect(() => {
    if (!isStreaming) return
    // Reset: assume user wants to follow the stream when it starts
    userScrolledUpRef.current = false

    const interval = setInterval(() => {
      const el = containerRef.current
      if (!el || userScrolledUpRef.current) return
      programmaticScrollRef.current = true
      el.scrollTop = el.scrollHeight
    }, 80)
    return () => clearInterval(interval)
  }, [isStreaming])

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    userScrolledUpRef.current = false
    programmaticScrollRef.current = true
    // Double rAF: wait for React render + browser layout
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (containerRef.current) {
          programmaticScrollRef.current = true
          containerRef.current.scrollTop = containerRef.current.scrollHeight
        }
      })
    })
  }, [])

  return { containerRef, showScrollButton, scrollToBottom }
}
