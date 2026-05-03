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
 *   - true → false (programmatic close): pop the store entry, then call
 *     `history.back()` to keep browser history in sync.
 *
 * Changes to `overlayId` while `open` stays true are intentionally
 * ignored — a Lightbox cycling through images does not deserve a new
 * back-button layer per image.
 *
 * The hook does not register a popstate listener of its own; the global
 * `BackButtonProvider` owns that responsibility.
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
    if (open && !registeredRef.current) {
      window.history.pushState({ __overlayId: overlayIdRef.current }, '')
      useHistoryStackStore
        .getState()
        .push(overlayIdRef.current, () => onCloseRef.current())
      registeredRef.current = true
      return
    }
    if (!open && registeredRef.current) {
      registeredRef.current = false
      const { wasTop } = removeOwnEntry(overlayIdRef.current)
      if (wasTop) {
        window.history.back()
      }
      return
    }
  }, [open])

  useEffect(() => {
    return () => {
      if (registeredRef.current) {
        registeredRef.current = false
        const { wasTop } = removeOwnEntry(overlayIdRef.current)
        if (wasTop) {
          window.history.back()
        }
      }
    }
  }, [])
}

function removeOwnEntry(overlayId: string): { removed: boolean; wasTop: boolean } {
  return useHistoryStackStore.getState().remove(overlayId)
}
