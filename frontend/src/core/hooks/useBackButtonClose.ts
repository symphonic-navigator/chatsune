import { useEffect, useRef } from 'react'
import { useHistoryStackStore } from '../store/historyStackStore'

let pendingTransitionFrom: string | null = null
let pendingRouteTransitionFrom: string | null = null

/**
 * Mark that a programmatic overlay close is happening because another overlay
 * is opening in the same tick. The next overlay to mount within this tick
 * will use replaceState (consuming the leaving overlay's browser history slot)
 * instead of pushState — so the browser ends up with one entry for "an
 * overlay is open" instead of two stacked phantoms whose mismatched popstate
 * would close the new overlay immediately.
 *
 * Auto-clears via setTimeout(0) if no overlay claims the transition (e.g.
 * the close happens during a route change rather than an overlay swap).
 */
export function startOverlayTransition(fromOverlayId: string): void {
  pendingTransitionFrom = fromOverlayId
  setTimeout(() => {
    if (pendingTransitionFrom === fromOverlayId) {
      pendingTransitionFrom = null
    }
  }, 0)
}

/**
 * Mark that a programmatic overlay close is happening because the
 * caller is navigating to a new route. The overlay's own cleanup will
 * skip its ``window.history.back()`` call when it sees a matching
 * pending transition — react-router has already pushed a new entry,
 * and an extra ``history.back()`` would race with it and revert the
 * URL.
 *
 * Auto-clears via ``setTimeout(0)`` if no overlay claims it (e.g. the
 * navigate ran but the overlay stays mounted).
 */
export function startRouteTransition(fromOverlayId: string): void {
  pendingRouteTransitionFrom = fromOverlayId
  setTimeout(() => {
    if (pendingRouteTransitionFrom === fromOverlayId) {
      pendingRouteTransitionFrom = null
    }
  }, 0)
}

/**
 * Synchronises an overlay's open state with a phantom browser-history
 * entry, so pressing browser back closes the overlay without changing
 * the route.
 *
 * Only the `open` transitions trigger history actions:
 *   - false → true: push a phantom history entry and register the
 *     overlay's onClose with `useHistoryStackStore`.
 *   - true → false (programmatic close, including unmount): pop the
 *     store entry, then call `history.back()` to keep browser history
 *     in sync.
 *
 * The push is deferred to a microtask so that React StrictMode's
 * double-invoke (mount → cleanup → mount) cancels the first push
 * before it fires. Without this, the cleanup's `history.back()` would
 * queue a popstate that races with the re-mount and the global
 * popstate handler would interpret it as a user-initiated back,
 * closing the overlay.
 *
 * Changes to `overlayId` while `open` stays true are intentionally
 * ignored — a Lightbox cycling through images does not deserve a new
 * back-button layer per image.
 *
 * The hook does not register a popstate listener of its own; the
 * global `BackButtonProvider` owns that responsibility.
 *
 * `overlayId` should be a stable string per overlay type (e.g.
 * `'user-modal'`, `'lightbox-chat'`).
 */
export function useBackButtonClose(
  open: boolean,
  onClose: () => void,
  overlayId: string,
): void {
  const registeredRef = useRef(false)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const overlayIdRef = useRef(overlayId)
  if (!registeredRef.current) {
    overlayIdRef.current = overlayId
  }

  useEffect(() => {
    if (!open) return

    let cancelled = false

    queueMicrotask(() => {
      if (cancelled) return
      if (pendingTransitionFrom !== null) {
        pendingTransitionFrom = null
        window.history.replaceState({ __overlayId: overlayIdRef.current }, '')
      } else {
        window.history.pushState({ __overlayId: overlayIdRef.current }, '')
      }
      useHistoryStackStore
        .getState()
        .push(overlayIdRef.current, () => onCloseRef.current())
      registeredRef.current = true
    })

    return () => {
      cancelled = true
      if (registeredRef.current) {
        registeredRef.current = false
        const { wasTop } = useHistoryStackStore
          .getState()
          .remove(overlayIdRef.current)
        const consumingRoute =
          pendingRouteTransitionFrom === overlayIdRef.current
        if (consumingRoute) {
          pendingRouteTransitionFrom = null
        }
        // When this overlay is the source of an overlay-to-overlay
        // transition, the incoming overlay will reuse our history slot
        // via ``replaceState``. Skipping ``history.back()`` here avoids
        // queuing a stale popstate that would otherwise pop the
        // incoming overlay off as soon as it mounts.
        const consumingOverlay =
          pendingTransitionFrom === overlayIdRef.current
        if (wasTop && !consumingRoute && !consumingOverlay) {
          window.history.back()
        }
      }
    }
  }, [open])
}
