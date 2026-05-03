import { useEffect, useRef } from 'react'
import { useHistoryStackStore } from '../store/historyStackStore'

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
      window.history.pushState({ __overlayId: overlayIdRef.current }, '')
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
        if (wasTop) {
          window.history.back()
        }
      }
    }
  }, [open])
}
