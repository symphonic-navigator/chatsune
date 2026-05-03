import { useEffect, type ReactNode } from 'react'
import { useHistoryStackStore } from '../store/historyStackStore'
import { useAuthStore } from '../store/authStore'

interface BackButtonProviderProps {
  children: ReactNode
}

/**
 * Mounts the single global popstate listener that drives overlay closes
 * on browser back. Also clears the overlay stack on logout so stale
 * onClose handlers cannot fire against unmounted components.
 *
 * This component renders its children unchanged — its only side-effect
 * is the listener. Mount it once near the root of the authenticated app.
 */
export function BackButtonProvider({ children }: BackButtonProviderProps) {
  useEffect(() => {
    function onPopState(event: PopStateEvent) {
      const top = useHistoryStackStore.getState().peek()
      const newStateId =
        (event.state && typeof event.state === 'object'
          ? (event.state as { __overlayId?: unknown }).__overlayId
          : undefined)

      if (top && top.overlayId !== newStateId) {
        useHistoryStackStore.getState().popTop()
        try {
          top.onClose()
        } catch (err) {
          console.error('[BackButtonProvider] onClose threw', err)
        }
        return
      }

      if (!top && typeof newStateId === 'string') {
        window.history.forward()
        return
      }
    }

    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    return useAuthStore.subscribe((state, prev) => {
      if (prev.isAuthenticated && !state.isAuthenticated) {
        useHistoryStackStore.getState().clear()
      }
    })
  }, [])

  return <>{children}</>
}
