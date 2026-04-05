import { useCallback, useEffect, useRef, useState } from 'react'

const SCROLL_THRESHOLD = 80

export function useAutoScroll(isStreaming: boolean) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  const userScrolledUpRef = useRef(false)
  const programmaticScrollRef = useRef(false)
  // Bump to re-run the scroll-listener effect when the ref attaches
  const [mounted, setMounted] = useState(0)

  // Callback to notify when containerRef attaches to the DOM
  const setContainerRef = useCallback((node: HTMLDivElement | null) => {
    (containerRef as React.MutableRefObject<HTMLDivElement | null>).current = node
    if (node) setMounted((n) => n + 1)
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
        programmaticScrollRef.current = false
        lastScrollTop = el.scrollTop
        return
      }

      if (el.scrollTop < lastScrollTop - 2) {
        userScrolledUpRef.current = true
      }
      if (nearBottom) {
        userScrolledUpRef.current = false
      }
      lastScrollTop = el.scrollTop
    }

    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [mounted])

  // Auto-scroll during streaming — use anchor element
  useEffect(() => {
    if (!isStreaming) return
    userScrolledUpRef.current = false

    const interval = setInterval(() => {
      if (userScrolledUpRef.current) return
      if (!bottomRef.current) return
      programmaticScrollRef.current = true
      bottomRef.current.scrollIntoView({ block: 'end' })
    }, 80)
    return () => clearInterval(interval)
  }, [isStreaming])

  const scrollToBottom = useCallback(() => {
    userScrolledUpRef.current = false
    programmaticScrollRef.current = true
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (bottomRef.current) {
          programmaticScrollRef.current = true
          bottomRef.current.scrollIntoView({ block: 'end', behavior: 'instant' })
        }
      })
    })
  }, [])

  return { containerRef: setContainerRef, bottomRef, showScrollButton, scrollToBottom }
}
