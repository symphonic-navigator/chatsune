import { useCallback, useEffect, useRef, useState } from 'react'

const SCROLL_THRESHOLD = 80

function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
}

/**
 * Auto-scroll hook for the chat transcript.
 *
 * Design notes — why this is not "poll isNearBottom every 80ms":
 *
 *   The naive approach ("if the container is still within N pixels of
 *   the bottom, scroll; otherwise leave it alone") cannot distinguish
 *   between "the user scrolled away" and "a single render added more
 *   than N pixels of content in one go" — which happens constantly
 *   during streaming (code blocks being syntax-highlighted, thinking
 *   blocks expanding, tool cards mounting, bursts of tokens, etc.).
 *   A single such jump permanently stops the polling auto-scroller
 *   even though the user did nothing, which is exactly what we saw
 *   in practice.
 *
 *   Instead we keep an explicit `following` flag. It starts true and
 *   is only flipped to false by a real scroll event — i.e. by the
 *   user. Content-initiated growth never touches it. A `MutationObserver`
 *   watches the scroll container and, while `following` is true, pins
 *   the viewport to the bottom after every DOM change, batched to one
 *   call per animation frame.
 *
 *   Programmatic `scrollIntoView` calls also fire a scroll event, but
 *   they always land at the bottom, so `isNearBottom` stays true and
 *   the scroll handler reaffirms `following = true` — no feedback loop.
 */
export function useAutoScroll() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)
  // Bump whenever the container ref attaches, so the effects below
  // re-run and bind to the freshly-mounted DOM node.
  const [mounted, setMounted] = useState(0)

  // `following` is stored in a ref, not in state, because the
  // MutationObserver callback below needs to read the latest value
  // synchronously without re-creating the observer on every flip.
  const followingRef = useRef(true)

  const setContainerRef = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node
    if (node) setMounted((n) => n + 1)
  }, [])

  // Scroll event: re-derive `following` and the scroll-to-bottom button
  // state from the live scroll position on every scroll, regardless of
  // whether the scroll was user-initiated or programmatic. Programmatic
  // scrolls always land at the bottom, so they re-set `following = true`
  // harmlessly. User scrolls that move away from the bottom set it to
  // false, and user scrolls back to the bottom set it to true again.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const onScroll = () => {
      const near = isNearBottom(el)
      followingRef.current = near
      setShowScrollButton(!near)
    }

    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [mounted])

  // Auto-follow: pin the viewport to the bottom on every DOM mutation
  // inside the scroll container, iff `following` is true. `MutationObserver`
  // fires after React has committed the update to the DOM, so reading
  // `scrollHeight` here is guaranteed to reflect the new content. We
  // debounce via `requestAnimationFrame` so a burst of mutations only
  // triggers one scroll per frame.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let rafId = 0
    const scheduleScroll = () => {
      if (!followingRef.current) return
      if (rafId !== 0) return
      rafId = requestAnimationFrame(() => {
        rafId = 0
        if (!followingRef.current) return
        bottomRef.current?.scrollIntoView({ block: 'end' })
      })
    }

    const observer = new MutationObserver(scheduleScroll)
    observer.observe(el, {
      childList: true,
      subtree: true,
      characterData: true,
    })

    // Kick off once so the first render after mount lands at the bottom.
    scheduleScroll()

    return () => {
      observer.disconnect()
      if (rafId !== 0) cancelAnimationFrame(rafId)
    }
  }, [mounted])

  const scrollToBottom = useCallback(() => {
    // Explicit user / caller request: resume following and jump to the
    // bottom. Two nested rAFs give React and the layout engine a chance
    // to flush any pending updates before we measure `scrollHeight`.
    followingRef.current = true
    setShowScrollButton(false)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ block: 'end', behavior: 'instant' })
      })
    })
  }, [])

  return { containerRef: setContainerRef, bottomRef, showScrollButton, scrollToBottom }
}
