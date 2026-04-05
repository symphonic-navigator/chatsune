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
        containerRef.current.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' })
      }
    }, 100)
    return () => clearInterval(interval)
  }, [isStreaming])

  const scrollToBottom = useCallback(() => {
    // Use requestAnimationFrame to ensure DOM has rendered before scrolling
    requestAnimationFrame(() => {
      containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' })
    })
  }, [])

  return { containerRef, showScrollButton, scrollToBottom }
}
