import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { useJobStore } from "../../core/store/jobStore"

/**
 * Subscribes the job store to the 'job.*' event stream. Mount exactly
 * once at the top of the authenticated tree (e.g. AppLayout), not per
 * view — otherwise events would be dispatched multiple times.
 */
export function useJobEvents() {
  useEffect(() => {
    const handler = useJobStore.getState().handleEvent
    const unsub = eventBus.on("job.*", handler)
    return () => {
      unsub()
    }
  }, [])
}
