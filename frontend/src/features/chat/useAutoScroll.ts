import { useCallback, useEffect, useRef, useState } from 'react'

const SCROLL_THRESHOLD = 80

function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
}

export function useAutoScroll(isStreaming: boolean) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  // Bump to re-run the scroll-listener effect when the ref attaches
  const [mounted, setMounted] = useState(0)

  // Callback to notify when containerRef attaches to the DOM
  const setContainerRef = useCallback((node: HTMLDivElement | null) => {
    (containerRef as React.MutableRefObject<HTMLDivElement | null>).current = node
    if (node) setMounted((n) => n + 1)
  }, [])

  // Scroll event — only used to toggle the "scroll to bottom" button
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    function onScroll() {
      const el = containerRef.current
      if (!el) return
      setShowScrollButton(!isNearBottom(el))
    }

    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [mounted])

  // Auto-scroll during streaming — only when the user is already at the bottom.
  // No "userScrolledUp" flag, no programmatic-scroll counter: we just sample
  // the live scroll position on every tick. If the user scrolls away, the
  // next tick sees it and stops following the stream. If they scroll back
  // down, following resumes automatically.
  useEffect(() => {
    if (!isStreaming) return

    const interval = setInterval(() => {
      const el = containerRef.current
      if (!el || !bottomRef.current) return
      if (!isNearBottom(el)) return
      bottomRef.current.scrollIntoView({ block: 'end' })
    }, 80)
    return () => clearInterval(interval)
  }, [isStreaming])

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ block: 'end', behavior: 'instant' })
      })
    })
  }, [])

  return { containerRef: setContainerRef, bottomRef, showScrollButton, scrollToBottom }
}
