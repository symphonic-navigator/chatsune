import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { usePullProgressStore } from "../../core/store/pullProgressStore"

/**
 * Subscribes the pull-progress store to the 'llm.model.pull.*' event stream.
 * Mount exactly once at the top of the authenticated tree (e.g. AppLayout).
 */
export function usePullProgressEvents() {
  useEffect(() => {
    const handler = usePullProgressStore.getState().handleEvent
    const unsub = eventBus.on("llm.model.pull.*", handler)
    return () => {
      unsub()
    }
  }, [])
}
