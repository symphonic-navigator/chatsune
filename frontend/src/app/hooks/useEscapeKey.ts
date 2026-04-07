import { useEffect } from "react"

/**
 * Invokes `callback` when the user presses the Escape key while `enabled`
 * is true. A reusable helper so overlays, modals, dropdowns and popovers
 * share a single, consistent Esc-to-close convention.
 *
 * Note: this listens on the document in the capture-less bubble phase, so
 * nested overlays that also use this hook will each receive the event. If
 * an outer overlay should defer to an inner one (nested modals), guard
 * the callback with state (see ModelSelectionModal for an example).
 */
export function useEscapeKey(callback: () => void, enabled: boolean = true): void {
  useEffect(() => {
    if (!enabled) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") callback()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [callback, enabled])
}
