import { useEffect } from 'react'

/**
 * Keep the device screen awake while `shouldHold` is `true`.
 *
 * Wraps the Screen Wake Lock API. Handles the browser's automatic release
 * when the tab becomes hidden by re-requesting on `visibilitychange` →
 * `visible`. On browsers without `navigator.wakeLock`, the hook is a silent
 * no-op; Conversational Mode still runs, the OS screen timeout just behaves
 * as usual.
 */
export function useWakeLock(shouldHold: boolean): void {
  useEffect(() => {
    if (!shouldHold) return
    if (!('wakeLock' in navigator)) return

    let sentinel: WakeLockSentinel | null = null
    let cancelled = false

    const acquire = async (): Promise<void> => {
      if (sentinel && !sentinel.released) return
      try {
        const fresh = await navigator.wakeLock.request('screen')
        if (cancelled) {
          await fresh.release()
          return
        }
        sentinel = fresh
      } catch (err) {
        // NotAllowedError fires if the document is not fully active (e.g.
        // acquire attempted while the page is transitioning). Not
        // user-actionable; debug-log and move on.
        console.debug('[useWakeLock] request failed:', err)
      }
    }

    const handleVisibilityChange = (): void => {
      if (document.visibilityState === 'visible') {
        void acquire()
      }
    }

    void acquire()
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      if (sentinel && !sentinel.released) {
        void sentinel.release()
      }
      sentinel = null
    }
  }, [shouldHold])
}
